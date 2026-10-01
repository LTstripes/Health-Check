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
$postModeById = @{}
$postQueriedIds = @()
$postModeQueryCountById = @{}
$taskkillDiagnosticMode = "lifecycle"
$taskkillTranscriptOverride = $null
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [object]$ErrorAction)
    if ($queryFailure -or ($postQueryFailure -and $identityMissing)) { throw "synthetic CIM identity query failure" }
    $ids = @($identityById.Keys)
    if ($Filter -match "^ProcessId=(\d+)$") { $ids = @([int]$Matches[1]) }
    elseif ($Filter) { throw "unexpected process identity query" }
    foreach ($id in $ids) {
        $mode = if ($identityMissing) { $postModeById[$id] } else { $null }
        if ($identityMissing -and $Filter) {
            $script:postQueriedIds += $id
            if ($mode -eq "transient_missing_command") {
                $seen = if ($script:postModeQueryCountById.ContainsKey($id)) { [int]$script:postModeQueryCountById[$id] } else { 0 }
                $script:postModeQueryCountById[$id] = $seen + 1
                if ($seen -gt 0) { continue }
            }
        }
        if ($mode -eq "query_error") { throw "synthetic per-PID query failure" }
        if ($identityMissing -and -not $mode -and ($id -eq 100 -or -not ($survivingChild -or $changedChild))) { continue }
        $value = $identityById[$id]
        if ($null -eq $value) { continue }
        [pscustomobject]@{
            ProcessId = $id
            ParentProcessId = if ($id -eq 100) { 1 } else { 100 }
            Name = if ($mode -in @("same_time_name", "reuse")) { "unrelated.exe" } else { $value.Name }
            CommandLine = if ($mode -eq "same_time_command") { "changed command" } elseif ($mode -in @("missing_command", "transient_missing_command")) { "" } else { $value.CommandLine }
            CreationDate = if ($mode -eq "missing_time") { $null } elseif ($mode -eq "malformed_time") { "invalid date" } else {
                [DateTime]::new([long]$value.CreationTime, [DateTimeKind]::Utc).AddSeconds($(if (($identityMissing -and $changedChild) -or $mode -eq "reuse") { 1 } else { 0 }))
            }
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
Assert-Equal 0 @($reusedChild.Errors).Count "proven child reuse must pass"
Assert-Equal "reused" $reusedChild.PostTerminationObservations[1].Classification "different CreationTime proves reuse"
$identityMissing = $false
$changedChild = $false
$postQueryFailure = $true
$unknownPost = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
Assert-True (@($unknownPost.Errors).Count -gt 0) "unknown post-termination identity must fail"
$identityMissing = $false
$postQueryFailure = $false
$identityCases = @("reuse", "same_time_name", "same_time_command", "missing_time", "malformed_time", "missing_command", "query_error", "alive")
foreach ($nativeCode in @(0, 255)) {
    $taskkillExitCode = $nativeCode
    foreach ($targetId in @(100, 101)) {
        foreach ($mode in $identityCases) {
            $identityMissing = $false
            $postModeById = @{ $targetId = $mode }
            $postQueriedIds = @()
            $taskkillCalls = @()
            $result = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
            Assert-Equal 1 $taskkillCalls.Count "post classification must not issue another kill"
            Assert-True ($postQueriedIds -contains 100 -and $postQueriedIds -contains 101) "every captured PID must be queried even after root reuse/failure"
            $record = @($result.PostTerminationObservations | Where-Object { $_.Id -eq $targetId })[0]
            if ($mode -eq "reuse") {
                Assert-Equal 0 @($result.Errors).Count "CreationTime proven reuse ($targetId) must pass"
                Assert-Equal "reused" $record.Classification "reuse classification"
                Assert-Equal $identityById[$targetId].CreationTime $record.CapturedCreationTime "captured time retained"
                Assert-True ($record.ObservedIdentity.CreationTime -ne $record.CapturedCreationTime) "observed different time retained"
            } else {
                Assert-True (@($result.Errors).Count -gt 0) "$mode ($targetId) must fail closed"
                Assert-Equal $(if ($mode -in @("alive", "missing_command")) { "same-identity-alive" } else { "unknown" }) $record.Classification "failure classification"
            }
        }
    }
    $identityMissing = $false
    $postModeById = @{ 100 = "reuse"; 101 = "alive" }
    $rootReuseWithSurvivor = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
    Assert-True (@($rootReuseWithSurvivor.RemainingOwnedProcessIds) -contains 101) "root reuse must not hide surviving captured child"
    Assert-True (@($rootReuseWithSurvivor.Errors).Count -gt 0) "root reuse with surviving child fails"
    $identityMissing = $false
    $postModeById = @{ 100 = "reuse"; 101 = "reuse" }
    $bothReused = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
    Assert-Equal 0 @($bothReused.Errors).Count "independently proven root and child reuse pass"
    $identityMissing = $false
    $postModeById = @{}
}

# Real runner evidence showed WMI can briefly return the same PID/CreationTime
# with an empty CommandLine immediately after taskkill, then report the PID absent.
# That is still the same captured instance and must keep bounded polling; it is
# never accepted as a terminal success while incomplete.
$taskkillExitCode = 0
$identityMissing = $false
$postModeById = @{ 100 = "transient_missing_command" }
$postModeQueryCountById = @{}
$postQueriedIds = @()
$transientIncomplete = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 1
Assert-Equal 0 @($transientIncomplete.Errors).Count "transient same-CreationTime incomplete identity must keep polling until absence"
Assert-True ([int]$postModeQueryCountById[100] -ge 2) "transient incomplete identity must be queried again"
$transientRoot = @($transientIncomplete.PostTerminationObservations | Where-Object { $_.Id -eq 100 })[0]
Assert-Equal "absent" $transientRoot.Classification "transient incomplete identity must finish only after captured PID is absent"
Assert-Equal 0 @($transientIncomplete.IdentityChangedProcessIds).Count "transient same-CreationTime incomplete identity is not PID reuse"
$identityMissing = $false
$postModeById = @{}
$postModeQueryCountById = @{}

$taskkillExitCode = 255
foreach ($invalidTime in @($null, "", "0", "01", "637134336000000001`n", "3155378976000000000", "99999999999999999999", 637134336000000001L)) {
    Assert-True (-not (Test-PostTerminationCreationTime $invalidTime)) "malformed/out-of-range/non-string creation time must fail"
}
Assert-True (Test-PostTerminationCreationTime "3155378975999999999") "DateTime maximum canonical ticks are valid"
Write-Output "Windows post-termination identity regressions PASS (36 lifecycle cases + creation-time grammar)"
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
