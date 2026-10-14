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
$parentById = @{}
$snapshotCreationById = @{}
$cimQueries = @()
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [object]$ErrorAction)
    $script:cimQueries += [string]$Filter
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
            ParentProcessId = if ($parentById.ContainsKey($id)) { $parentById[$id] } elseif ($id -eq $capturedRoot.Id) { 1 } else { $capturedRoot.Id }
            Name = if ($mode -in @("same_time_name", "reuse")) { "unrelated.exe" } else { $value.Name }
            CommandLine = if ($mode -eq "same_time_command") { "changed command" } elseif ($mode -in @("missing_command", "transient_missing_command")) { "" } else { $value.CommandLine }
            CreationDate = if (-not $Filter -and $snapshotCreationById.ContainsKey($id)) { $snapshotCreationById[$id] } elseif ($mode -eq "missing_time") { $null } elseif ($mode -eq "malformed_time") { "invalid date" } else {
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
    if ($null -ne $taskkillTranscriptOverride) {
        if ($exitDuringTermination) { $script:identityMissing = $true }
        return $taskkillTranscriptOverride
    }
    if ($taskkillExitCode -eq 255) {
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
Assert-Equal $null $successfulTermination.OwnershipSnapshotDiagnostic "valid tree has no failure diagnostic"
$identityMissing = $false

# Both refusals must retain only the offending edge from the same snapshot,
# including a deeper edge. Filtered child requery would see a valid timestamp.
foreach ($deep in @($false, $true)) {
    foreach ($reason in @("child_creation_missing", "child_predates_parent")) {
        $identityById[101] = [pscustomobject]@{ Id = 101; Name = "python.exe"; CommandLine = "synthetic child"; CreationTime = "637134336010000000" }
        $identityById[102] = [pscustomobject]@{ Id = 102; Name = "python.exe"; CommandLine = "synthetic grandchild"; CreationTime = "637134336020000000" }
        $parentById = @{ 102 = 101 }
        $childId = if ($deep) { 102 } else { 101 }
        $parentId = if ($deep) { 101 } else { 100 }
        $olderTicks = ([long]$identityById[$parentId].CreationTime - 1).ToString()
        $snapshotCreationById = @{ $childId = if ($reason -eq "child_creation_missing") { $null } else { [DateTime]::new([long]$olderTicks, [DateTimeKind]::Utc) } }
        $taskkillCalls = @()
        $cimQueries = @()
        $result = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
        Assert-Equal "failed" $result.Outcome "snapshot refusal remains failed ($deep/$reason)"
        Assert-True (-not $result.TerminationIssued) "snapshot refusal cannot issue termination"
        Assert-Equal 0 $taskkillCalls.Count "snapshot refusal has zero native calls"
        Assert-Equal 0 @($result.OwnedProcessIdentities).Count "partial traversal cannot promote ownership"
        Assert-Equal 0 @($result.PostTerminationObservations).Count "no post-termination proof is invented"
        Assert-Equal $null $result.TaskkillExitCode "no native exit code is invented"
        Assert-Equal 0 @($result.TaskkillOutput).Count "no native transcript is invented"
        Assert-Equal 1 @($result.Errors).Count "original refusal remains the only error"
        Assert-Equal "ambiguous descendant ownership (reused parent PID)" $result.Errors[0] "original refusal retained"
        Assert-Equal 2 $cimQueries.Count "only initial root query and one snapshot; no diagnostic requery"
        Assert-Equal "ProcessId=100" $cimQueries[0] "initial query targets captured root"
        Assert-Equal "" $cimQueries[1] "one coherent snapshot"
        $json = $result.OwnershipSnapshotDiagnostic | ConvertTo-Json -Depth 8 -Compress
        $diagnostic = $json | ConvertFrom-Json
        Assert-Equal $reason $diagnostic.Reason "distinct snapshot reason retained"
        Assert-Equal 100 $diagnostic.CapturedRoot.Id "captured root PID retained"
        Assert-Equal $capturedRoot.CreationTime $diagnostic.CapturedRoot.CreationTime "captured root ticks retained"
        Assert-Equal $parentId $diagnostic.Parent.Id "offending parent PID retained"
        Assert-Equal $(if ($deep) { 100 } else { 1 }) $diagnostic.Parent.ParentProcessId "parent edge retained"
        Assert-Equal $identityById[$parentId].CreationTime $diagnostic.Parent.CreationTime "same snapshot parent ticks retained"
        Assert-Equal $childId $diagnostic.Child.Id "offending child PID retained"
        Assert-Equal $parentId $diagnostic.Child.ParentProcessId "child edge retained"
        Assert-Equal ($reason -ne "child_creation_missing") $diagnostic.Child.CreationTimePresent "child timestamp presence retained"
        Assert-Equal ($reason -ne "child_creation_missing") $diagnostic.Child.CreationTimeValid "child timestamp validity retained"
        Assert-Equal $(if ($reason -eq "child_creation_missing") { $null } else { $olderTicks }) $diagnostic.Child.CreationTime "no invented or requeried child time"
        Assert-Equal $(if ($reason -eq "child_creation_missing") { "missing" } else { "valid" }) $diagnostic.Child.CreationTimeState "child timestamp classification"
        foreach ($record in @($diagnostic.CapturedRoot, $diagnostic.Parent, $diagnostic.Child)) {
            Assert-True ($record.IdPresent -and $record.IdValid) "diagnostic ID flags retained"
        }
        foreach ($record in @($diagnostic.CapturedRoot, $diagnostic.Parent)) {
            Assert-True ($record.CreationTimePresent -and $record.CreationTimeValid) "parent/root timestamp flags retained"
        }
        foreach ($record in @($diagnostic.Parent, $diagnostic.Child)) {
            Assert-True ($record.ParentProcessIdPresent -and $record.ParentProcessIdValid) "parent edge flags retained"
        }
        Assert-Equal "CapturedRoot,Child,Parent,Reason" (($diagnostic.PSObject.Properties.Name | Sort-Object) -join ',') "diagnostic contains only one edge and root"
        Assert-True ($json -notmatch 'Name|CommandLine|synthetic child|synthetic grandchild') "diagnostic contains no process text"
    }
}
$snapshotCreationById = @{ 102 = 0 }
$taskkillCalls = @()
$cimQueries = @()
$invalidTimeRefusal = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
Assert-Equal "failed" $invalidTimeRefusal.Outcome "failed diagnostic conversion cannot waive refusal"
Assert-Equal 0 $taskkillCalls.Count "failed diagnostic conversion has zero native calls"
Assert-True (-not $invalidTimeRefusal.TerminationIssued) "invalid time cannot authorize termination"
Assert-Equal 0 @($invalidTimeRefusal.OwnedProcessIdentities).Count "invalid time cannot promote ownership"
Assert-Equal 2 $cimQueries.Count "failed conversion cannot requery"
Assert-Equal "ambiguous descendant ownership (reused parent PID)" $invalidTimeRefusal.Errors[0] "failed diagnostic conversion preserves original refusal"
Assert-Equal "child_creation_missing" $invalidTimeRefusal.OwnershipSnapshotDiagnostic.Reason "false-valued invalid time preserves guard reason"
Assert-Equal "invalid" $invalidTimeRefusal.OwnershipSnapshotDiagnostic.Child.CreationTimeState "failed conversion retains invalid classification"
Assert-Equal $null $invalidTimeRefusal.OwnershipSnapshotDiagnostic.Child.CreationTime "failed conversion retains unavailable ticks"
$invalidDiagnostic = Get-OwnershipDiagnosticIdentity ([pscustomobject]@{ ProcessId = "invalid"; ParentProcessId = $null; CreationDate = "invalid date" })
Assert-True ($invalidDiagnostic.IdPresent -and -not $invalidDiagnostic.IdValid) "invalid diagnostic ID stays unavailable"
Assert-True (-not $invalidDiagnostic.ParentProcessIdPresent -and -not $invalidDiagnostic.ParentProcessIdValid) "missing diagnostic parent ID stays unavailable"
Assert-True ($invalidDiagnostic.CreationTimePresent -and -not $invalidDiagnostic.CreationTimeValid) "failed timestamp conversion is invalid"
Assert-Equal "invalid" $invalidDiagnostic.CreationTimeState "conversion failure classification retained"
Assert-Equal $null $invalidDiagnostic.CreationTime "conversion failure cannot invent ticks"
$snapshotCreationById = @{}
$parentById = @{}
$identityById.Remove(101)
$identityById.Remove(102)
Write-Output "Windows ownership snapshot refusal regressions PASS (5 same-snapshot cases, invalid conversion)"

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

# Retained #243 shape: seven child SUCCESS records, child ERROR + Reason,
# exactly one empty item, then root SUCCESS. Synthetic replay proves parser
# behavior, not whether native taskkill or stream merging emitted the item.
$matrix = Get-Content (Join-Path $PSScriptRoot "fixtures\ci_windows_exit255_transcripts.json") -Raw | ConvertFrom-Json
foreach ($id in 102..108) {
    $identityById[$id] = [pscustomobject]@{ Id = $id; Name = "python.exe"; CommandLine = "synthetic child $id"; CreationTime = "637134336010000000" }
}
foreach ($case in $matrix.cases) {
    $separator = if ($null -ne $case.separator_index) { [int]$case.separator_index } else { 9 }
    if ($case.accepted -and $null -ne $case.separator_index) {
        Assert-True ($case.output[$separator] -is [string]) "accepted separator must be an actual string"
        Assert-Equal 0 $case.output[$separator].Length "accepted separator must have Length == 0"
    }
    if ($null -ne $case.separator_codepoint) {
        Assert-True ($case.output[$separator] -is [string]) "Unicode separator must be a string"
        Assert-Equal 1 $case.output[$separator].Length "Unicode negative must be nonempty"
        Assert-Equal $case.separator_codepoint ([int][char]$case.output[$separator][0]) "Unicode separator code point"
        Assert-Equal $false $case.accepted "Unicode separator must be a negative case"
    }
    $identityMissing = $false
    $taskkillCalls = @()
    $postQueriedIds = @()
    $taskkillTranscriptOverride = @($case.output)
    $result = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
    $accepted = $result.Outcome -eq "exited-during-termination" -and @($result.Errors).Count -eq 0
    Assert-Equal $case.accepted $accepted "retained transcript case $($case.name)"
    Assert-Equal 1 $taskkillCalls.Count "retained transcript uses one root-scoped kill"
    Assert-Equal 9 @($result.PostTerminationObservations).Count "all captured PIDs independently observed"
    Assert-Equal ($case.output | ConvertTo-Json -Compress) ($result.TaskkillOutput | ConvertTo-Json -Compress) "raw transcript retained"
    if ($null -ne $case.separator_codepoint) {
        Write-Output ("PowerShell Unicode U+{0:X4}: length=1 rejected" -f [int]$case.separator_codepoint)
    }
}
foreach ($case in $matrix.cases | Where-Object { $_.name -in @("retained_shape", "observed_one_sibling_suffix") }) {
    $taskkillTranscriptOverride = @($case.output)
    foreach ($targetId in @(100, 102, 103, 108)) {
        foreach ($mode in $identityCases) {
            $identityMissing = $false
            $postModeById = @{ $targetId = $mode }
            $postQueriedIds = @()
            $taskkillCalls = @()
            $result = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
            Assert-Equal ($mode -eq "reuse") ($result.Outcome -eq "exited-during-termination") "separator preserves identity contract ($($case.name)/$targetId/$mode)"
            Assert-Equal 1 $taskkillCalls.Count "separator identity checks issue one kill"
            Assert-Equal "100" $taskkillCalls[0] "separator identity checks retain root ownership"
            Assert-Equal 9 @($result.PostTerminationObservations).Count "separator checks all captured identities"
            foreach ($id in 100..108) { Assert-True ($postQueriedIds -contains $id) "separator independently queries PID $id" }
        }
    }
    $identityMissing = $false
    $postModeById = @{ 100 = "reuse"; 108 = "alive" }
    $result = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
    Assert-True (@($result.Errors).Count -gt 0) "root reuse cannot hide surviving child with separator"
    $postModeById = @{}
    foreach ($code in @(1, 5, 254, 256, -1)) {
        $identityMissing = $false
        $taskkillExitCode = $code
        $taskkillCalls = @()
        $result = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
        Assert-True (@($result.Errors).Count -gt 0) "other nonzero code $code fails even with accepted transcript and absent tree"
        Assert-Equal "failed" $result.Outcome "other nonzero code cannot be waived"
        Assert-True $result.LifecycleDiagnosticVerified "exact transcript cannot waive another nonzero code"
        Assert-Equal 1 $taskkillCalls.Count "other nonzero code uses one kill"
    }
    $taskkillExitCode = 255
}
$taskkillExitCode = 255
$taskkillTranscriptOverride = $null
$identityMissing = $false
foreach ($id in 102..108) { $identityById.Remove($id) }
Write-Output "Windows retained separator regressions PASS ($($matrix.cases.Count) transcripts + 66 identity cases + 10 nonzero codes)"

# New native128 shape has a separate matrix; old exit255 inputs remain unchanged.
$exit128 = Get-Content (Join-Path $PSScriptRoot "fixtures\ci_windows_exit128_transcripts.json") -Raw | ConvertFrom-Json
function Set-Exit128SyntheticCase {
    param([object]$Case)
    $script:identityById = @{}
    $owned = if ($null -ne $Case.owned) { $Case.owned } else { $exit128.owned }
    foreach ($identity in $owned) {
        $script:identityById[[int]$identity.Id] = $identity | Select-Object *
    }
    foreach ($change in @($Case.identity_updates)) {
        if ($null -ne $change) {
            $script:identityById[[int]$owned[$change.index].Id].($change.field) = $change.value
        }
    }
    $script:exit128Owned = @($owned | ForEach-Object { $script:identityById[[int]$_.Id] })
    $script:capturedRoot = $script:identityById[[int]$owned[0].Id]
    $parents = if ($null -ne $Case.parents) { $Case.parents } else { $exit128.parents }
    $script:parentById = @{}
    foreach ($property in $parents.PSObject.Properties) { $script:parentById[[int]$property.Name] = [int]$property.Value }
    $items = [Collections.Generic.List[object]]::new()
    $output = if ($null -ne $Case.output) { $Case.output } else { $exit128.output }
    foreach ($item in $output) { $items.Add($item) }
    $changes = @($Case.output_changes)
    for ($index = $changes.Count - 1; $index -ge 0; $index--) {
        $change = $changes[$index]
        if ($null -eq $change) { continue }
        $items.RemoveRange([int]$change.start, [int]($change.end - $change.start))
        $items.InsertRange([int]$change.start, [object[]]@($change.items))
    }
    $script:taskkillTranscriptOverride = $items.ToArray()
    $script:identityMissing = $false
    $script:postModeById = @{}
    $script:postQueriedIds = @()
    $script:taskkillCalls = @()
    $script:taskkillExitCode = 128
    $script:exitDuringTermination = $true
}
foreach ($case in $exit128.cases) {
    Set-Exit128SyntheticCase $case
    Assert-Equal $case.accepted (Test-Exit128LifecycleTranscript $taskkillTranscriptOverride $exit128Owned) "exit128 direct parser case $($case.name)"
    # Native capture already converts emitted items to strings. Exercise malformed
    # artifact types at the pure parser boundary, without normalizing test inputs.
    if (@($taskkillTranscriptOverride | Where-Object { $_ -isnot [string] }).Count -gt 0) { continue }
    $before = $taskkillTranscriptOverride | ConvertTo-Json -Compress
    $result = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
    $accepted = $result.Outcome -eq "exited-during-termination" -and @($result.Errors).Count -eq 0
    Assert-Equal $case.accepted $accepted "exit128 case $($case.name)"
    if ($result.TerminationIssued) {
        Assert-True ([string]::Equals($before, ($result.TaskkillOutput | ConvertTo-Json -Compress), [StringComparison]::Ordinal)) "exit128 raw items retained when issued"
    }
    Assert-True ($taskkillCalls.Count -le 1) "exit128 cannot issue a second kill"
    if ($case.accepted) {
        Assert-Equal 1 $taskkillCalls.Count "accepted128 issues one verified-root kill"
        Assert-Equal 9 @($result.PostTerminationObservations).Count "accepted128 observes every captured identity"
    }
}
$identity128Checks = 0
foreach ($targetId in 100..108) {
    foreach ($mode in $identityCases) {
        Set-Exit128SyntheticCase $exit128.cases[0]
        $postModeById = @{ $targetId = $mode }
        $result = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
        Assert-Equal ($mode -eq "reuse") ($result.Outcome -eq "exited-during-termination") "exit128 preserves identity boundary ($targetId/$mode)"
        Assert-Equal 1 $taskkillCalls.Count "exit128 identity check uses one root kill"
        foreach ($id in 100..108) { Assert-True ($postQueriedIds -contains $id) "exit128 independently queries PID $id" }
        $identity128Checks++
    }
}
foreach ($code in @(1, 5, 127, 129, 254, 255, 256, -1)) {
    Set-Exit128SyntheticCase $exit128.cases[0]
    $taskkillExitCode = $code
    $result = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
    Assert-Equal "failed" $result.Outcome "two-separator shape cannot waive another nonzero code $code"
}
Set-Exit128SyntheticCase $exit128.cases[0]
$postModeById = @{ 100 = "reuse"; 108 = "alive" }
$result = Invoke-RootProcessTreeTermination $capturedRoot -PostTimeoutSeconds 0
Assert-Equal "failed" $result.Outcome "exit128 root reuse cannot hide a surviving child"
Write-Output "Windows exit128 regressions PASS ($($exit128.cases.Count) shared cases, $identity128Checks per-identity cases, 8 other nonzero codes)"
$identityById = @{ 100 = [pscustomobject]@{ Id = 100; Name = "pwsh.exe"; CommandLine = "start.ps1 -DataDir root"; CreationTime = "637134336000000000" } }
$capturedRoot = $identityById[100]
$parentById = @{}
$postModeById = @{}
$taskkillTranscriptOverride = $null
$identityMissing = $false
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

# This standalone suite uses the same matrix and the full Python artifact
# validation entry point; keep workflow/routing/manifest ownership unchanged.
& (Join-Path $repoRoot ".venv\Scripts\python.exe") (Join-Path $PSScriptRoot "ci_windows_transcript_regressions.py")
if ($LASTEXITCODE -ne 0) { throw "Python Windows transcript/evidence regressions failed" }
