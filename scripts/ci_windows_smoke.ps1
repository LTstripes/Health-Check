[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$EvidenceDir
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$evidenceRoot = [IO.Path]::GetFullPath($EvidenceDir)
$repoPrefix = $repoRoot.TrimEnd('\') + '\'
if ($evidenceRoot.Equals($repoRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $evidenceRoot.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Windows smoke evidence must be outside the checkout: $evidenceRoot"
}
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null

$runtimeRoot = Join-Path ([IO.Path]::GetTempPath()) ("healthcheck-ci-windows-smoke-" + [guid]::NewGuid().ToString("N"))
if ($runtimeRoot.Equals($repoRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $runtimeRoot.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Windows smoke runtime must be outside the checkout: $runtimeRoot"
}
$junitPath = Join-Path $evidenceRoot "dpapi.junit.xml"
$stdoutPath = Join-Path $evidenceRoot "start.stdout.log"
$stderrPath = Join-Path $evidenceRoot "start.stderr.log"
$cleanupPath = Join-Path $evidenceRoot "cleanup.json"
$evidencePath = Join-Path $evidenceRoot "smoke-evidence.json"
$harness = $null
$status = "failed"
$failure = $null
$httpEvidence = $null
$dpapiEvidence = $null
$cleanupEvidence = $null
$runtimeRemoved = $false
$processIdentityErrors = @()
. (Join-Path $PSScriptRoot "ci_windows_process.ps1")

function Add-ProcessIdentityErrors([object[]]$Errors) {
    foreach ($errorText in @($Errors)) {
        if ($errorText) { $script:processIdentityErrors += [string]$errorText }
    }
}

function Write-JsonFile([string]$Path, [object]$Value) {
    try {
        $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding utf8 -ErrorAction Stop
        return $null
    } catch {
        return $_.Exception.Message
    }
}

try {
    Push-Location $repoRoot
    if (Test-Path -LiteralPath $runtimeRoot) { throw "synthetic runtime path already exists" }
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = ([Net.IPEndPoint]$listener.LocalEndpoint).Port
    $listener.Stop()

    $startArguments = @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\start.ps1"),
        "-DataDir", $runtimeRoot,
        "-Port", "$port"
    )
    $harness = Start-Process -FilePath "pwsh" -ArgumentList $startArguments `
        -WorkingDirectory $repoRoot -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath -WindowStyle Hidden -PassThru

    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ($true) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 3
            $body = $response.Content | ConvertFrom-Json
            if ($response.StatusCode -eq 200 -and $body.status -eq "ok" -and $body.service -eq "loopback-ui") {
                $httpEvidence = [ordered]@{
                    host = "127.0.0.1"
                    path = "/healthz"
                    status_code = [int]$response.StatusCode
                    body = [ordered]@{ service = [string]$body.service; status = [string]$body.status }
                }
                break
            }
        } catch {
            if ($harness.HasExited) { throw "PowerShell start harness exited before loopback smoke succeeded" }
            if ([DateTime]::UtcNow -ge $deadline) { throw "loopback HTTP smoke timed out" }
        }
        Start-Sleep -Milliseconds 500
    }

    & uv run pytest -q "tests/test_garmin_auth.py::test_windows_user_scoped_protection_round_trips_and_rejects_owner_tampering" `
        "--junitxml=$junitPath" 2>&1 | Tee-Object -FilePath (Join-Path $evidenceRoot "dpapi.log")
    $dpapiExit = $LASTEXITCODE
    if ($dpapiExit -ne 0) { throw "native DPAPI pytest exited with $dpapiExit" }
    [xml]$junit = Get-Content -LiteralPath $junitPath -Raw
    $suite = @($junit.testsuites.testsuite)
    if (-not $suite) { $suite = @($junit.testsuite) }
    $tests = [int](($suite | Measure-Object -Property tests -Sum).Sum)
    $failures = [int](($suite | Measure-Object -Property failures -Sum).Sum)
    $errors = [int](($suite | Measure-Object -Property errors -Sum).Sum)
    $skipped = [int](($suite | Measure-Object -Property skipped -Sum).Sum)
    if ($tests -ne 1 -or $failures -ne 0 -or $errors -ne 0 -or $skipped -ne 0) {
        throw "native DPAPI evidence was not exactly one passed, non-skipped test"
    }
    $dpapiEvidence = [ordered]@{
        nodeid = "tests/test_garmin_auth.py::test_windows_user_scoped_protection_round_trips_and_rejects_owner_tampering"
        outcome = "passed"
        counts = [ordered]@{ tests = $tests; failures = $failures; errors = $errors; skipped = $skipped }
    }
    $status = "passed"
} catch {
    $failure = $_.Exception.Message
} finally {
    $cleanupErrors = @()
    $ownedBefore = @()
    $remaining = @()
    $terminatedProcessIds = @()
    $identityChangedProcessIds = @()
    $rootPid = if ($harness) { [int]$harness.Id } else { 0 }
    try {
        $snapshotResult = Get-ProcessSnapshot
        Add-ProcessIdentityErrors $snapshotResult.Errors
        $snapshot = @($snapshotResult.Processes)
        if ($harness) {
            $ownedResult = Get-OwnedProcessSnapshot $harness.Id $snapshot
            Add-ProcessIdentityErrors $ownedResult.Errors
            $ownedBefore = @($ownedResult.Processes)
            $stopResult = Stop-OwnedProcesses $ownedBefore
            $terminatedProcessIds = @($stopResult.TerminatedProcessIds)
            $identityChangedProcessIds = @($stopResult.IdentityChangedProcessIds)
            $cleanupErrors += @($stopResult.Errors)
            Start-Sleep -Milliseconds 250
            $afterResult = Get-ProcessSnapshot
            Add-ProcessIdentityErrors $afterResult.Errors
            $after = @($afterResult.Processes)
            foreach ($candidate in @($ownedBefore)) {
                $current = $after | Where-Object Id -eq $candidate.Id
                if ($current -and [string]$current.Name -eq [string]$candidate.Name -and
                    [string]$current.CommandLine -eq [string]$candidate.CommandLine) {
                    $remaining += [int]$candidate.Id
                }
            }
        }
    } catch {
        $cleanupErrors += "cleanup traversal failed: $($_.Exception.Message)"
    }
    $cleanupEvidence = [ordered]@{
        scope = "harness-root-and-descendants-only"
        root_pid = $rootPid
        started_process_ids = @($ownedBefore | ForEach-Object { [int]$_.Id } | Sort-Object -Unique)
        terminated_process_ids = $terminatedProcessIds
        remaining_owned_process_ids = @($remaining | Sort-Object -Unique)
        identity_changed_process_ids = $identityChangedProcessIds
        errors = @($cleanupErrors)
    }
    try {
        if (Test-Path -LiteralPath $runtimeRoot) {
            Remove-Item -LiteralPath $runtimeRoot -Recurse -Force -ErrorAction Stop
        }
    } catch {
        $cleanupErrors += "synthetic runtime cleanup failed: $($_.Exception.Message)"
    }
    try {
        $runtimeRemoved = -not (Test-Path -LiteralPath $runtimeRoot -ErrorAction Stop)
    } catch {
        $runtimeRemoved = $false
        $cleanupErrors += "synthetic runtime existence check failed: $($_.Exception.Message)"
    }
    $cleanupEvidence.errors = @($cleanupErrors)
    $processIdentityError = if ($processIdentityErrors.Count -gt 0) {
        $processIdentityErrors -join "; "
    } else { $null }
    if ($cleanupEvidence.remaining_owned_process_ids.Count -ne 0 -or
        $cleanupEvidence.identity_changed_process_ids.Count -ne 0 -or
        $cleanupEvidence.errors.Count -ne 0 -or
        -not $runtimeRemoved -or $processIdentityError) {
        $status = "failed"
        if (-not $failure) {
            $failure = "owned harness cleanup or process identity evidence was incomplete"
        }
    }
    $cleanupWriteError = Write-JsonFile $cleanupPath $cleanupEvidence
    if ($cleanupWriteError) {
        $processIdentityErrors += "cleanup.json write failed: $cleanupWriteError"
        $status = "failed"
        if (-not $failure) { $failure = "cleanup evidence could not be written" }
    }
    try {
        $headSha = (& git rev-parse HEAD).Trim()
        $treeSha = (& git rev-parse "HEAD^{tree}").Trim()
        $gitClean = [string]::IsNullOrWhiteSpace((& git status --porcelain))
    } catch {
        $headSha = "unknown"
        $treeSha = "unknown"
        $gitClean = $false
        $processIdentityErrors += "git evidence failed: $($_.Exception.Message)"
        $status = "failed"
        if (-not $failure) { $failure = "git evidence could not be written" }
    }
    $evidence = [ordered]@{
        schema_version = 1
        status = $status
        failure = $failure
        platform = "win32"
        runner = "Windows/X64"
        event_name = $env:GITHUB_EVENT_NAME
        ref = $env:GITHUB_REF
        pr_base_ref = if ($env:GITHUB_BASE_REF) { $env:GITHUB_BASE_REF } else { "" }
        pr_base_sha = if ($env:PR_BASE_SHA) { $env:PR_BASE_SHA } else { "" }
        pr_head_ref = if ($env:GITHUB_HEAD_REF) { $env:GITHUB_HEAD_REF } else { "" }
        pr_head_sha = if ($env:PR_HEAD_SHA) { $env:PR_HEAD_SHA } else { "" }
        head_sha = $headSha
        tree_sha = $treeSha
        checked_out_head = $headSha
        checked_out_tree = $treeSha
        git_clean = $gitClean
        powershell = [ordered]@{ version = $PSVersionTable.PSVersion.ToString() }
        runtime = [ordered]@{ outside_checkout = $true; removed = $runtimeRemoved }
        http = $httpEvidence
        dpapi = $dpapiEvidence
        cleanup = $cleanupEvidence
        process_snapshot_error = if ($processIdentityErrors.Count -gt 0) {
            $processIdentityErrors -join "; "
        } else { $null }
    }
    [void](Write-JsonFile $evidencePath $evidence)
    try { Pop-Location } catch { }
}

if ($status -ne "passed") { throw "Windows smoke failed: $failure" }
