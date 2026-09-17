[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$EvidenceDir
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "ci_windows_process.ps1")

function Write-JsonFile([string]$Path, [object]$Value) {
    try {
        $Value | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $Path -Encoding utf8 -ErrorAction Stop
        return $null
    } catch {
        return $_.Exception.Message
    }
}

function Get-FreeLoopbackPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([Net.IPEndPoint]$listener.LocalEndpoint).Port
    } finally {
        $listener.Stop()
    }
}

function Get-HttpResponseEvidence {
    param(
        [string]$Uri,
        [ValidateSet("GET", "POST")]
        [string]$Method = "GET"
    )

    try {
        $request = @{
            UseBasicParsing = $true
            Uri = $Uri
            Method = $Method
            TimeoutSec = 3
            ErrorAction = "Stop"
        }
        if ($Method -eq "POST") {
            $request.Body = "{}"
            $request.ContentType = "application/json"
        }
        $response = Invoke-WebRequest @request
        $body = $null
        try { $body = $response.Content | ConvertFrom-Json } catch { }
        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Body = $body
            Error = $null
        }
    } catch {
        $statusCode = $null
        if ($_.Exception.Response) {
            try { $statusCode = [int]$_.Exception.Response.StatusCode } catch { }
        }
        return [pscustomobject]@{
            StatusCode = $statusCode
            Body = $null
            Error = $_.Exception.Message
        }
    }
}

function Wait-Health {
    param(
        [string]$Uri,
        [string]$ExpectedService,
        [System.Diagnostics.Process]$Harness
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $deadline) {
        $response = Get-HttpResponseEvidence $Uri
        if ($response.StatusCode -eq 200 -and $response.Body -and
            $response.Body.status -eq "ok" -and $response.Body.service -eq $ExpectedService) {
            return [ordered]@{
                host = "127.0.0.1"
                path = "/healthz"
                status_code = 200
                body = [ordered]@{
                    service = [string]$response.Body.service
                    status = [string]$response.Body.status
                }
            }
        }
        if ($Harness -and $Harness.HasExited) {
            throw "PowerShell start harness exited before $ExpectedService loopback smoke succeeded"
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$ExpectedService loopback HTTP smoke timed out"
}

function Invoke-SmokeScenario {
    param(
        [string]$ScenarioName,
        [bool]$EnableIngest,
        [string]$EvidenceRoot
    )

    $scenarioDir = Join-Path $EvidenceRoot $ScenarioName
    New-Item -ItemType Directory -Force -Path $scenarioDir | Out-Null
    $runtimeRoot = Join-Path ([IO.Path]::GetTempPath()) ("Health Check CI 125 " + [guid]::NewGuid().ToString("N") + " " + $ScenarioName)
    $uiPort = Get-FreeLoopbackPort
    $ingestPort = Get-FreeLoopbackPort
    while ($ingestPort -eq $uiPort) { $ingestPort = Get-FreeLoopbackPort }
    $stdoutPath = Join-Path $scenarioDir "start.stdout.log"
    $stderrPath = Join-Path $scenarioDir "start.stderr.log"
    $harness = $null
    $capturedRoot = $null
    $failure = $null
    $runtimeRemoved = $false
    $identityErrors = @()
    $uiHealth = $null
    $ingestHealth = $null
    $surfaceEvidence = [ordered]@{
        ui_host = "127.0.0.1"
        ui_port = $uiPort
        ingest_host = "127.0.0.1"
        ingest_port = $ingestPort
        ui_health = $null
        ingest_health = $null
        ui_ingest_route_status = $null
        ingest_openscale_get_status = $null
        ingest_port_closed_before_start = $false
    }
    $cleanup = [ordered]@{
        scope = "verified-root-process-tree-only"
        root_pid = 0
        root_name = ""
        root_command_line = ""
        root_identity_verified = $false
        termination = "taskkill /PID <verified-root> /T /F"
        termination_issued = $false
        root_already_exited = $false
        remaining_owned_process_ids = @()
        identity_changed_process_ids = @()
        ports_closed = [ordered]@{ ui = $false; ingest = $false }
        errors = @()
    }

    try {
        $runtimeRoot = Assert-ExternalRuntimePath $repoRoot $runtimeRoot
        if ($runtimeRoot -notmatch "\s") { throw "scenario runtime path does not contain spaces" }
        $uiBefore = Get-LoopbackPortEvidence $uiPort
        $ingestBefore = Get-LoopbackPortEvidence $ingestPort
        if (-not $uiBefore.Closed -or -not $ingestBefore.Closed) {
            throw "scenario ports were already listening before startup"
        }
        $surfaceEvidence.ingest_port_closed_before_start = [bool]$ingestBefore.Closed

        $startArguments = @(
            "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $repoRoot "scripts\start.ps1"),
            "-DataDir", ('"' + $runtimeRoot + '"'),
            "-Port", "$uiPort",
            "-IngestHost", "127.0.0.1",
            "-IngestPort", "$ingestPort"
        )
        if ($EnableIngest) { $startArguments += "-EnableIngest" }
        $harness = Start-Process -FilePath "pwsh" -ArgumentList $startArguments `
            -WorkingDirectory $repoRoot -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath -WindowStyle Hidden -PassThru
        $capturedRoot = Get-ProcessIdentity $harness.Id
        if ($capturedRoot.QueryError) {
            $identityErrors += [string]$capturedRoot.QueryError
            throw "root identity could not be established: $($capturedRoot.QueryError)"
        }
        if (-not $capturedRoot.Exists -or -not (Test-CapturedProcessIdentity $capturedRoot)) {
            $identityErrors += "root identity was absent or incomplete after startup"
            throw "root identity was absent or incomplete after startup"
        }
        $cleanup.root_pid = [int]$capturedRoot.Id
        $cleanup.root_name = [string]$capturedRoot.Name
        $cleanup.root_command_line = [string]$capturedRoot.CommandLine
        $cleanup.root_identity_verified = $true

        $uiHealth = Wait-Health "http://127.0.0.1:$uiPort/healthz" "loopback-ui" $harness
        $surfaceEvidence.ui_health = $uiHealth
        if ($EnableIngest) {
            $ingestHealth = Wait-Health "http://127.0.0.1:$ingestPort/healthz" "ingest" $harness
            $surfaceEvidence.ingest_health = $ingestHealth
            $uiRoute = Get-HttpResponseEvidence "http://127.0.0.1:$uiPort/api/ingest/openscale" "POST"
            $ingestRoute = Get-HttpResponseEvidence "http://127.0.0.1:$ingestPort/api/ingest/openscale" "GET"
            $surfaceEvidence.ui_ingest_route_status = $uiRoute.StatusCode
            $surfaceEvidence.ingest_openscale_get_status = $ingestRoute.StatusCode
            if ($uiRoute.StatusCode -ne 404 -or $ingestRoute.StatusCode -ne 405) {
                throw "UI/ingest route separation did not match the existing route contract"
            }
        } else {
            $ingestClosed = Get-LoopbackPortEvidence $ingestPort
            if (-not $ingestClosed.Closed) { throw "disabled ingest port was listening" }
        }
    } catch {
        $failure = $_.Exception.Message
    } finally {
        if ($capturedRoot) {
            $termination = Invoke-RootProcessTreeTermination $capturedRoot
            $cleanup.termination_issued = [bool]$termination.TerminationIssued
            $cleanup.root_already_exited = [bool]$termination.RootAlreadyExited
            $cleanup.identity_changed_process_ids = @($termination.IdentityChangedProcessIds)
            $cleanup.errors += @($termination.Errors)
            Start-Sleep -Milliseconds 300
            $postRoot = Get-ProcessIdentity $capturedRoot.Id
            if ($postRoot.QueryError) {
                $cleanup.errors += [string]$postRoot.QueryError
            } elseif ($postRoot.Exists) {
                if (Test-SameProcessIdentity $capturedRoot $postRoot) {
                    $cleanup.remaining_owned_process_ids += [int]$capturedRoot.Id
                } else {
                    $cleanup.identity_changed_process_ids += [int]$capturedRoot.Id
                }
            }
        } elseif ($harness) {
            $cleanup.errors += "root identity was not established; destructive cleanup was not attempted"
        }

        $uiAfter = Get-LoopbackPortEvidence $uiPort
        $ingestAfter = Get-LoopbackPortEvidence $ingestPort
        $cleanup.ports_closed.ui = [bool]$uiAfter.Closed
        $cleanup.ports_closed.ingest = [bool]$ingestAfter.Closed
        if (-not $uiAfter.Closed) { $cleanup.errors += "UI loopback port $uiPort remained open" }
        if (-not $ingestAfter.Closed) { $cleanup.errors += "ingest loopback port $ingestPort remained open" }

        try {
            if (Test-Path -LiteralPath $runtimeRoot) {
                Remove-Item -LiteralPath $runtimeRoot -Recurse -Force -ErrorAction Stop
            }
        } catch {
            $cleanup.errors += "synthetic runtime cleanup failed: $($_.Exception.Message)"
        }
        try {
            $runtimeRemoved = -not (Test-Path -LiteralPath $runtimeRoot -ErrorAction Stop)
        } catch {
            $runtimeRemoved = $false
            $cleanup.errors += "synthetic runtime existence check failed: $($_.Exception.Message)"
        }
        $cleanup.remaining_owned_process_ids = @($cleanup.remaining_owned_process_ids | Sort-Object -Unique)
        $cleanup.identity_changed_process_ids = @($cleanup.identity_changed_process_ids | Sort-Object -Unique)
        $cleanup.errors = @($cleanup.errors)
    }

    $status = if ($failure -or $cleanup.errors.Count -gt 0 -or
        $cleanup.remaining_owned_process_ids.Count -gt 0 -or
        -not $cleanup.ports_closed.ui -or -not $cleanup.ports_closed.ingest -or
        -not $runtimeRemoved) { "failed" } else { "passed" }
    return [ordered]@{
        name = $ScenarioName
        status = $status
        failure = $failure
        runtime = [ordered]@{
            path = $runtimeRoot
            outside_checkout = $true
            path_contains_spaces = ($runtimeRoot -match "\s")
            removed = $runtimeRemoved
        }
        surfaces = $surfaceEvidence
        cleanup = $cleanup
        identity_errors = @($identityErrors)
    }
}

$evidenceRoot = [IO.Path]::GetFullPath($EvidenceDir)
$repoPrefix = $repoRoot.TrimEnd('\') + '\'
if ($evidenceRoot.Equals($repoRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $evidenceRoot.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Windows smoke evidence must be outside the checkout: $evidenceRoot"
}
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
$junitPath = Join-Path $evidenceRoot "dpapi.junit.xml"
$cleanupPath = Join-Path $evidenceRoot "cleanup.json"
$evidencePath = Join-Path $evidenceRoot "smoke-evidence.json"
$status = "failed"
$failure = $null
$dpapiEvidence = $null
$scenarios = @()
$processIdentityErrors = @()
$runtimeEvidence = [ordered]@{ outside_checkout = $true; path_contains_spaces = $true; removed = $false }
$cleanupEvidence = [ordered]@{
    scope = "verified-root-process-tree-only"
    root_pid = 0
    started_process_ids = @()
    terminated_process_ids = @()
    remaining_owned_process_ids = @()
    identity_changed_process_ids = @()
    errors = @()
    scenarios = @()
}

try {
    Push-Location $repoRoot
    $scenarios += ,(Invoke-SmokeScenario "ingest-disabled" $false $evidenceRoot)
    $scenarios += ,(Invoke-SmokeScenario "ingest-enabled" $true $evidenceRoot)
    $processIdentityErrors += @($scenarios | ForEach-Object { $_.identity_errors })
    if (@($scenarios | Where-Object { $_.status -ne "passed" }).Count -gt 0) {
        throw "one or more Windows smoke scenarios failed"
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
    $scenarioCleanups = @($scenarios | ForEach-Object { $_.cleanup })
    foreach ($scenarioCleanup in $scenarioCleanups) {
        if ($cleanupEvidence.root_pid -eq 0 -and $scenarioCleanup.root_pid -gt 0) {
            $cleanupEvidence.root_pid = [int]$scenarioCleanup.root_pid
        }
        if ($scenarioCleanup.root_pid -gt 0) { $cleanupEvidence.started_process_ids += [int]$scenarioCleanup.root_pid }
        if ($scenarioCleanup.termination_issued -and $scenarioCleanup.root_pid -gt 0) {
            $cleanupEvidence.terminated_process_ids += [int]$scenarioCleanup.root_pid
        }
        $cleanupEvidence.remaining_owned_process_ids += @($scenarioCleanup.remaining_owned_process_ids)
        $cleanupEvidence.identity_changed_process_ids += @($scenarioCleanup.identity_changed_process_ids)
        $cleanupEvidence.errors += @($scenarioCleanup.errors)
    }
    $cleanupEvidence.started_process_ids = @($cleanupEvidence.started_process_ids | Sort-Object -Unique)
    $cleanupEvidence.terminated_process_ids = @($cleanupEvidence.terminated_process_ids | Sort-Object -Unique)
    $cleanupEvidence.remaining_owned_process_ids = @($cleanupEvidence.remaining_owned_process_ids | Sort-Object -Unique)
    $cleanupEvidence.identity_changed_process_ids = @($cleanupEvidence.identity_changed_process_ids | Sort-Object -Unique)
    $cleanupEvidence.errors = @($cleanupEvidence.errors)
    $cleanupEvidence.scenarios = @($scenarioCleanups)
    $runtimeEvidence.removed = @($scenarios | Where-Object { $_.runtime.removed -ne $true }).Count -eq 0
    if ($cleanupEvidence.remaining_owned_process_ids.Count -gt 0 -or
        $cleanupEvidence.errors.Count -gt 0 -or -not $runtimeEvidence.removed) {
        $status = "failed"
        if (-not $failure) { $failure = "Windows root-tree cleanup or runtime evidence was incomplete" }
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
        schema_version = 2
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
        runtime = $runtimeEvidence
        http = if (@($scenarios).Count -gt 0) { $scenarios[0].surfaces.ui_health } else { $null }
        scenarios = @($scenarios)
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
