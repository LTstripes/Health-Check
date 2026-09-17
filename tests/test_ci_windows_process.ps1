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

$systemSnapshot = @(
    [pscustomobject]@{ Id = 10; ParentId = 1; Name = "pwsh.exe"; CommandLine = "root" }
    [pscustomobject]@{ Id = 11; ParentId = 10; Name = "python.exe"; CommandLine = "child" }
    [pscustomobject]@{ Id = 0; ParentId = 0; Name = "Idle"; CommandLine = "" }
    [pscustomobject]@{ Id = 4; ParentId = 0; Name = "System"; CommandLine = "" }
    [pscustomobject]@{ Id = $null; ParentId = 0; Name = "malformed.exe"; CommandLine = "unrelated" }
    [pscustomobject]@{ Id = 13; ParentId = $null; Name = "incomplete.exe"; CommandLine = "unrelated" }
)
$owned = Get-OwnedProcessSnapshot 10 $systemSnapshot
Assert-Equal 2 @($owned.Processes).Count "missing parent bucket must not expand ownership"
Assert-True (@($owned.Processes | ForEach-Object Id) -contains 10) "root process must be retained"
Assert-True (@($owned.Processes | ForEach-Object Id) -contains 11) "verified child must be retained"
Assert-Equal 0 @($owned.Errors).Count "unrelated system or malformed records must not block ownership"

$identityById = @{
    100 = [pscustomobject]@{ Id = 100; Name = "pwsh.exe"; CommandLine = "root" }
    2 = [pscustomobject]@{ Id = 2; Name = "python.exe"; CommandLine = "child" }
    90 = [pscustomobject]@{ Id = 90; Name = "python.exe"; CommandLine = "grandchild" }
}
$queryFailure = $false
$stopOrder = @()
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [object]$ErrorAction)
    if ($queryFailure) { throw "synthetic CIM identity query failure" }
    if ($Filter -match "ProcessId=(\d+)") { return $identityById[[int]$Matches[1]] }
    throw "unexpected process snapshot query"
}
function Stop-Process {
    param([int]$Id, [switch]$Force, [object]$ErrorAction)
    $script:stopOrder += $Id
}

$orderedOwned = @(
    [pscustomobject]@{ Id = 100; Name = "pwsh.exe"; CommandLine = "root" }
    [pscustomobject]@{ Id = 2; Name = "python.exe"; CommandLine = "child" }
    [pscustomobject]@{ Id = 90; Name = "python.exe"; CommandLine = "grandchild" }
)
$orderedCleanup = Stop-OwnedProcesses $orderedOwned
Assert-Equal "90,2,100" ($stopOrder -join ",") "deepest owned process must stop before root regardless of PID order"
Assert-Equal 0 @($orderedCleanup.Errors).Count "verified cleanup order must have no errors"

$identityById[90] = [pscustomobject]@{ Id = 90; Name = "unrelated.exe"; CommandLine = "reused" }
$stopOrder = @()
$reusedCleanup = Stop-OwnedProcesses $orderedOwned
Assert-True (@($reusedCleanup.IdentityChangedProcessIds) -contains 90) "reused PID must be reported"
Assert-True (-not (@($stopOrder) -contains 90)) "reused PID must never be terminated"
Assert-Equal 0 @($reusedCleanup.Errors).Count "safe reused PID must not be a cleanup error"

$queryFailure = $true
$queryFailureCleanup = Stop-OwnedProcesses @(
    [pscustomobject]@{ Id = 90; Name = "python.exe"; CommandLine = "grandchild" }
)
$queryFailure = $false
Assert-True (@($queryFailureCleanup.Errors).Count -gt 0) "CIM identity query failure must fail closed"
$identityById[90] = $null
$naturalExitCleanup = Stop-OwnedProcesses @(
    [pscustomobject]@{ Id = 90; Name = "python.exe"; CommandLine = "grandchild" }
)
Assert-Equal 0 @($naturalExitCleanup.Errors).Count "missing process is safe after natural exit"
$identityById[90] = [pscustomobject]@{ Id = 90; Name = "python.exe"; CommandLine = "grandchild" }

$ownedMalformed = Get-OwnedProcessSnapshot 10 @(
    [pscustomobject]@{ Id = 10; ParentId = 1; Name = "pwsh.exe"; CommandLine = "root" }
    [pscustomobject]@{ Id = $null; ParentId = 10; Name = "malformed.exe"; CommandLine = "owned" }
)
Assert-True (@($ownedMalformed.Errors).Count -gt 0) "malformed owned relation must fail closed"

$missingRoot = Get-OwnedProcessSnapshot 10 @(
    [pscustomobject]@{ Id = 4; ParentId = 0; Name = "System"; CommandLine = "" }
)
Assert-True (@($missingRoot.Errors).Count -gt 0) "missing harness root must fail closed"

$empty = Get-OwnedProcessSnapshot 10 @()
Assert-Equal 0 @($empty.Processes).Count "empty snapshot must produce no owned processes"
Assert-Equal 0 @($empty.Errors).Count "an already-exited root is safe with an empty snapshot"

$invalidCleanup = Stop-OwnedProcesses @(
    [pscustomobject]@{ Id = $null; Name = "pwsh.exe"; CommandLine = "root" }
)
Assert-Equal 0 @($invalidCleanup.TerminatedProcessIds).Count "invalid identity must never terminate a process"
Assert-True (@($invalidCleanup.Errors).Count -gt 0) "invalid identity must produce cleanup evidence"

$emptyCollectionsJson = [ordered]@{
    terminated_process_ids = @($invalidCleanup.TerminatedProcessIds)
    identity_changed_process_ids = @($invalidCleanup.IdentityChangedProcessIds)
    errors = @()
} | ConvertTo-Json -Depth 4
$emptyCollections = $emptyCollectionsJson | ConvertFrom-Json
Assert-True ($emptyCollections.terminated_process_ids -is [array]) "empty terminated IDs must serialize as an array"
Assert-True ($emptyCollections.identity_changed_process_ids -is [array]) "empty changed IDs must serialize as an array"
Assert-True ($emptyCollections.errors -is [array]) "empty cleanup errors must serialize as an array"

Write-Output "Windows process traversal regression PASS"
