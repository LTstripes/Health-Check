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
    100 = [pscustomobject]@{ Id = 100; Name = "pwsh.exe"; CommandLine = "start.ps1 -DataDir root" }
}
$queryFailure = $false
$identityMissing = $false
$taskkillExitCode = 0
$taskkillCalls = @()
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [object]$ErrorAction)
    if ($queryFailure) { throw "synthetic CIM identity query failure" }
    if ($identityMissing) { return }
    if ($Filter -match "ProcessId=(\d+)") { return $identityById[[int]$Matches[1]] }
    throw "unexpected process identity query"
}
function taskkill.exe {
    param([Parameter(ValueFromRemainingArguments = $true)][object[]]$Arguments)
    $script:taskkillCalls += [string]$Arguments[1]
    $global:LASTEXITCODE = $taskkillExitCode
}

$capturedRoot = [pscustomobject]@{
    Id = 100
    Name = "pwsh.exe"
    CommandLine = "start.ps1 -DataDir root"
}
$successfulTermination = Invoke-RootProcessTreeTermination $capturedRoot
Assert-Equal 1 @($taskkillCalls).Count "verified root tree must use one native termination call"
Assert-Equal "100" $taskkillCalls[0] "native termination must target the verified root PID"
Assert-True $successfulTermination.TerminationIssued "verified root tree termination must be recorded"
Assert-Equal 0 @($successfulTermination.Errors).Count "successful root tree termination must have no errors"

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
Assert-Equal 0 @($naturalExit.Errors).Count "already-exited root must not create a descendant cleanup error"

$identityById[100] = $capturedRoot
$queryFailure = $true
$queryFailed = Invoke-RootProcessTreeTermination $capturedRoot
$queryFailure = $false
Assert-True (@($queryFailed.Errors).Count -gt 0) "root identity query failure must fail closed"

Write-Output "Windows root-tree lifecycle regression PASS"
