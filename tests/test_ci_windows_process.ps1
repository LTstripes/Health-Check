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

$partialSnapshot = @(
    [pscustomobject]@{ Id = 10; ParentId = 1; Name = "pwsh.exe"; CommandLine = "root" }
    [pscustomobject]@{ Id = 11; ParentId = 10; Name = "python.exe"; CommandLine = "child" }
    [pscustomobject]@{ Id = 12; ParentId = 999; Name = "unrelated.exe"; CommandLine = "leaf" }
    [pscustomobject]@{ Id = 13; ParentId = $null; Name = "incomplete.exe"; CommandLine = "partial" }
)
$owned = Get-OwnedProcessSnapshot 10 $partialSnapshot
Assert-Equal 2 @($owned.Processes).Count "missing parent bucket must not expand ownership"
Assert-True (@($owned.Processes | ForEach-Object Id) -contains 10) "root process must be retained"
Assert-True (@($owned.Processes | ForEach-Object Id) -contains 11) "verified child must be retained"
Assert-True (@($owned.Errors).Count -gt 0) "partial process relation must fail closed"

$empty = Get-OwnedProcessSnapshot 10 @()
Assert-Equal 0 @($empty.Processes).Count "empty snapshot must produce no owned processes"
Assert-Equal 0 @($empty.Errors).Count "an already-exited root is safe with an empty snapshot"

$invalidCleanup = Stop-OwnedProcesses @(
    [pscustomobject]@{ Id = $null; Name = "pwsh.exe"; CommandLine = "root" }
)
Assert-Equal 0 @($invalidCleanup.TerminatedProcessIds).Count "invalid identity must never terminate a process"
Assert-True (@($invalidCleanup.Errors).Count -gt 0) "invalid identity must produce cleanup evidence"

Write-Output "Windows process traversal regression PASS"
