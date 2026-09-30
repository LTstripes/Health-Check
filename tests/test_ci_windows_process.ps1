$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\scripts\ci_windows_process.ps1")

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "assertion failed: $Message" }
}

function Assert-Equal([object]$Expected, [object]$Actual, [string]$Message) {
    if ($Expected -ne $Actual) {
        throw "assertion failed: $Message (expected '$Expected', got '$Actual')"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
try {
    Assert-ExternalRuntimePath $repoRoot $repoRoot | Out-Null
    throw "checkout-local runtime path was accepted"
} catch {
    Assert-True ($_.Exception.Message -match "outside the checkout") "checkout-local runtime path must be rejected"
}
try {
    Assert-ExternalRuntimePath $repoRoot (Join-Path $repoRoot "nested") | Out-Null
    throw "checkout-child runtime path was accepted"
} catch {
    Assert-True ($_.Exception.Message -match "outside the checkout") "checkout-child runtime path must be rejected"
}

$identityById = @{
    100 = [pscustomobject]@{ Id = 100; Name = "pwsh.exe"; CommandLine = "start.ps1 -DataDir root"; CreationTime = "637134336000000000" }
}
$queryFailure = $false
$identityMissing = $false
$taskkillExitCode = 0
$taskkillCalls = @()
$exitDuringTermination = $false
$postQueryFailure = $false
$survivingChild = $false
$changedChild = $false
$taskkillDiagnosticMode = "lifecycle"
$taskkillTranscriptOverride = $null
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [object]$ErrorAction)
    if ($queryFailure -or ($postQueryFailure -and $identityMissing)) { throw "synthetic CIM identity query failure" }
    $ids = @($identityById.Keys)
    if ($Filter -match "^ProcessId=(\d+)$") { $ids = @([int]$Matches[1]) }
    elseif ($Filter) { throw "unexpected process identity query" }
    foreach ($id in $ids) {
        if ($identityMissing -and ($id -eq 100 -or -not ($survivingChild -or $changedChild))) { continue }
        $value = $identityById[$id]
        if ($null -eq $value) { continue }
        [pscustomobject]@{
            ProcessId = $id
            ParentProcessId = if ($id -eq 100) { 1 } else { 100 }
            Name = $value.Name
            CommandLine = $value.CommandLine
            CreationDate = [DateTime]::new([long]$value.CreationTime, [DateTimeKind]::Utc).AddSeconds($(if ($identityMissing -and $changedChild) { 1 } else { 0 }))
        }
    }
}
function taskkill.exe {
    param([Parameter(ValueFromRemainingArguments = $true)][object[]]$Arguments)
    $script:taskkillCalls += [string]$Arguments[1]
    $global:LASTEXITCODE = $taskkillExitCode
    if ($taskkillExitCode -eq 0 -or ($taskkillExitCode -eq 255 -and $exitDuringTermination)) { $script:identityMissing = $true }
    if ($taskkillExitCode -eq 255) {
        if ($null -ne $taskkillTranscriptOverride) { return $taskkillTranscriptOverride }
        if ($taskkillDiagnosticMode -ne "empty") {
            "ERROR: The process with PID 100 (child process of PID 1) could not be terminated."
            if ($taskkillDiagnosticMode -eq "access-denied") { "Reason: Access is denied." }
            else { "Reason: There is no running instance of the task." }
            foreach ($id in $identityById.Keys | Where-Object { $_ -ne 100 }) {
                "SUCCESS: The process with PID $id (child process of PID 100) has been terminated."
            }
        }
    } else { "synthetic taskkill tree result $taskkillExitCode" }
}

$capturedRoot = [pscustomobject]@{
    Id = 100
    Name = "pwsh.exe"
    CommandLine = "start.ps1 -DataDir root"
    CreationTime = "637134336000000000"
}
$successfulTermination = Invoke-RootProcessTreeTermination $capturedRoot
Assert-Equal 1 @($taskkillCalls).Count "verified root tree must use one native termination call"
Assert-Equal "100" $taskkillCalls[0] "native termination must target the verified root PID"
Assert-True $successfulTermination.TerminationIssued "verified root tree termination must be recorded"
Assert-Equal 0 @($successfulTermination.Errors).Count "successful root tree termination must have no errors"
$identityMissing = $false

$taskkillCalls = @()
$identityById[100] = [pscustomobject]@{ Id = 100; Name = "unrelated.exe"; CommandLine = "reused" }
$mismatchTermination = Invoke-RootProcessTreeTermination $capturedRoot
Assert-Equal 0 @($taskkillCalls).Count "root identity mismatch must never invoke taskkill"
Assert-True (@($mismatchTermination.IdentityChangedProcessIds) -contains 100) "root identity mismatch must be recorded"
Assert-True (@($mismatchTermination.Errors).Count -gt 0) "root identity mismatch must fail closed"

$identityById[100] = $capturedRoot
$taskkillExitCode = 5
$failedTermination = Invoke-RootProcessTreeTermination $capturedRoot
Assert-True (@($failedTermination.Errors).Count -gt 0) "root-tree termination failure must be fatal"
$taskkillExitCode = 0

$identityMissing = $true
$naturalExit = Invoke-RootProcessTreeTermination $capturedRoot
$identityMissing = $false
Assert-True $naturalExit.RootAlreadyExited "already-exited root must be recognized"
Assert-True (@($naturalExit.Errors).Count -gt 0) "root absent before ownership snapshot must leave descendant cleanup unproven"

$identityById[100] = $capturedRoot
$queryFailure = $true
$queryFailed = Invoke-RootProcessTreeTermination $capturedRoot
$queryFailure = $false
Assert-True (@($queryFailed.Errors).Count -gt 0) "root identity query failure must fail closed"

$exitDuringTermination = $true
$taskkillExitCode = 255
$racedTermination = Invoke-RootProcessTreeTermination $capturedRoot
Assert-Equal 0 @($racedTermination.Errors).Count "verified tree absent after exit 255 must have a distinct lifecycle result"
Assert-Equal "exited-during-termination" $racedTermination.Outcome "exit race must not be relabeled native success"
$identityMissing = $false
$exitDuringTermination = $false
$liveTermination = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
Assert-True (@($liveTermination.Errors).Count -gt 0) "255 with a surviving owned process must fail"

$identityById[101] = [pscustomobject]@{ Id = 101; Name = "python.exe"; CommandLine = "synthetic child"; CreationTime = "637134336010000000" }
$exitDuringTermination = $true
$childRace = Invoke-RootProcessTreeTermination $capturedRoot
Assert-Equal 2 @($childRace.OwnedProcessIdentities).Count "tree snapshot must retain child ownership"
Assert-Equal "exited-during-termination" $childRace.Outcome "fully absent owned tree may reconcile 255"
$identityMissing = $false
$survivingChild = $true
$orphan = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
Assert-True (@($orphan.RemainingOwnedProcessIds) -contains 101) "orphaned child must be checked after root exit"
Assert-True (@($orphan.Errors).Count -gt 0) "surviving child must fail even with absent root"
$identityMissing = $false
$survivingChild = $false
$changedChild = $true
$reusedChild = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
Assert-True (@($reusedChild.IdentityChangedProcessIds) -contains 101) "same-command PID reuse must compare creation time"
Assert-True (@($reusedChild.Errors).Count -gt 0) "reused child must fail"
$identityMissing = $false
$changedChild = $false
$postQueryFailure = $true
$unknownPost = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
Assert-True (@($unknownPost.Errors).Count -gt 0) "unknown post-termination identity must fail"
$identityMissing = $false
$postQueryFailure = $false
foreach ($mode in @("empty", "access-denied")) {
    $taskkillDiagnosticMode = $mode
    $badDiagnostic = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
    Assert-True (@($badDiagnostic.Errors).Count -gt 0) "255 without exact native lifecycle diagnostic must fail"
    $identityMissing = $false
}
$taskkillDiagnosticMode = "lifecycle"
$exactError = "ERROR: The process with PID 100 (child process of PID 1) could not be terminated."
$exactReason = "Reason: There is no running instance of the task."
$exactSuccess = "SUCCESS: The process with PID 101 (child process of PID 100) has been terminated."
$transcripts = [ordered]@{
    valid = @($exactError, $exactReason, $exactSuccess)
    valid_native_order = @($exactSuccess, $exactError, $exactReason)
    valid_all_errors = @($exactError, $exactReason, "ERROR: The process with PID 101 (child process of PID 100) could not be terminated.", $exactReason)
    missing_record = @($exactError, $exactReason)
    reason_trailing = @($exactError, "$exactReason UNRECOGNIZED_DIAGNOSTIC", $exactSuccess)
    unknown_line = @($exactError, $exactReason, $exactSuccess, "UNRECOGNIZED_DIAGNOSTIC")
    malformed_success = @($exactError, $exactReason, "SUCCESS: The process with PID 101 nonsense")
    incomplete_error = @($exactError, $exactSuccess)
    malformed_reason = @($exactError, "Reason: There is no running instance of the task", $exactSuccess)
    malformed_error = @("ERROR: The process with PID 100 nonsense could not be terminated.", $exactReason, $exactSuccess)
    duplicate_success = @($exactError, $exactReason, $exactSuccess, $exactSuccess)
    duplicate_error = @($exactError, $exactReason, $exactError, $exactReason, $exactSuccess)
    unexpected_record = @($exactError, $exactReason, $exactSuccess, "SUCCESS: The process with PID 102 (child process of PID 100) has been terminated.")
    error_trailing = @("$exactError garbage", $exactReason, $exactSuccess)
    success_trailing = @($exactError, $exactReason, "$exactSuccess garbage")
    orphan_reason = @($exactError, $exactReason, $exactSuccess, $exactReason)
    blank_line = @($exactError, $exactReason, "", $exactSuccess)
    case_changed = @($exactError.ToLowerInvariant(), $exactReason, $exactSuccess)
    embedded_newline = @($exactError, $exactReason, "$exactSuccess`nUNKNOWN")
    trailing_newline = @($exactError, "$exactReason`n", $exactSuccess)
    trailing_carriage_return = @($exactError, "$exactReason`r", $exactSuccess)
    success_only = @("SUCCESS: The process with PID 100 (child process of PID 1) has been terminated.", $exactSuccess)
}
$transcriptFailures = @()
foreach ($case in $transcripts.Keys) {
    $identityMissing = $false
    $taskkillTranscriptOverride = $transcripts[$case]
    $result = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
    $accepted = $result.Outcome -eq "exited-during-termination" -and @($result.Errors).Count -eq 0
    if ($accepted -ne ($case -in @("valid", "valid_native_order", "valid_all_errors"))) { $transcriptFailures += $case }
}
$taskkillTranscriptOverride = $null
$identityMissing = $false
Assert-Equal 0 $transcriptFailures.Count "complete-transcript cases failed: $($transcriptFailures -join ', ')"
Write-Output "Windows complete-transcript regressions PASS ($($transcripts.Count) cases)"
$exitDuringTermination = $false
$taskkillExitCode = 0

$freeProbeListener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
try {
    $freeProbeListener.Start()
    $freePort = ([Net.IPEndPoint]$freeProbeListener.LocalEndpoint).Port
} finally {
    $freeProbeListener.Stop()
}
$freeProbe = Get-LoopbackPortEvidence $freePort
Assert-True $freeProbe.Closed "released loopback port must be reported as closed"
Assert-Equal $null $freeProbe.Error "released loopback port must have no probe error"

$listeningProbeListener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
try {
    $listeningProbeListener.Start()
    $listeningPort = ([Net.IPEndPoint]$listeningProbeListener.LocalEndpoint).Port
    $listeningProbe = Get-LoopbackPortEvidence $listeningPort
    Assert-True (-not $listeningProbe.Closed) "listening loopback port must be reported as open"
    Assert-Equal $null $listeningProbe.Error "listening loopback port must have no probe error"
} finally {
    $listeningProbeListener.Stop()
}

Write-Output "Windows root-tree lifecycle regression PASS"
