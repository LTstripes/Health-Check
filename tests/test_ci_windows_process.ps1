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
