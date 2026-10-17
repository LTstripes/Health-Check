# Synthetic contract counterexamples and fault boundaries; not production acceptance.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$FixtureParent,
      [Parameter(Mandatory=$true)][string]$EvidencePath)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$source=Join-Path $PSScriptRoot 'probes\workspace_recycle_probe.cs'
Add-Type -Path $source
$safeParent=[IO.Path]::GetFullPath($FixtureParent).TrimEnd('\')
$junctionFactory=[Action[string,string]]{
    param($link,$target)
    $prefix=[regex]::Escape($safeParent)+'\\workspace-recycle-contract-[a-f0-9]{32}\\junction-after-check\\'
    if($link -cnotmatch ('^'+$prefix+'source$') -or $target -cnotmatch ('^'+$prefix+'decoy$')){throw 'Owned junction fixture boundary rejected'}
    if(Test-Path -LiteralPath $link){throw 'Junction source collision'}
    New-Item -ItemType Junction -Path $link -Target $target -ErrorAction Stop | Out-Null
}
try {
    $result=[WorkspaceRecycleProbe.Probe]::RunContracts($safeParent,$junctionFactory)
    if($result.Cases.Count -ne 5 -or @($result.Cases|Where-Object {-not $_.DecoyPreserved}).Count -ne 0){throw 'Contract case coverage incomplete'}
    foreach($name in @('replacement-after-check','junction-after-check')){
        if(-not ($result.Cases|Where-Object {$_.Name -eq $name}).HookRan){throw 'Race injection was not exercised'}
    }
    $partial=$result.Cases|Where-Object {$_.Name -eq 'cancel-after-move'}
    if($partial.OperationAccepted -or -not $partial.ReceiptPresent -or -not $partial.Restored){throw 'Post-move failure handling was not proved'}
    $probeSource=Get-Content -LiteralPath $source -Raw
    if($probeSource -match '\b(DeleteFile\w*|RemoveDirectory\w*|SetFileInformationByHandle|SHEmptyRecycleBin\w*)\s*\(' -or $probeSource -match '\b(File|Directory)\.Delete\s*\('){throw 'Unexpected permanent deletion/bin-empty primitive in probe'}
    $receipt=[ordered]@{utc=[datetime]::UtcNow.ToString('o');status='PASS_BOUNDARY_EVIDENCE;PRODUCTION_NO_GO';harness_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash;source_sha256=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash;process=$PSVersionTable.PSVersion.ToString();apartment=[Threading.Thread]::CurrentThread.ApartmentState.ToString();result=$result;production_ready=$false;real_workspace_operations=0;permanent_fallback=$false;permanent_primitive_source_audit='PASS';bin_emptied_or_enumerated=$false;limits='Owned small synthetic cases;not a general tree/quota/crash-recovery proof'}
    $receipt|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $EvidencePath -Encoding UTF8
    $receipt|ConvertTo-Json -Depth 8
} catch {
    [ordered]@{utc=[datetime]::UtcNow.ToString('o');status='FAILED_KEEP_OWN_FIXTURES_NO_RETRY';source_sha256=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash;fixture_group=[WorkspaceRecycleProbe.Probe]::LastContractGroup;failure=$_.Exception.GetBaseException().Message;production_ready=$false}|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $EvidencePath -Encoding UTF8
    throw
}
