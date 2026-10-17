# Synthetic-only feasibility evidence, NOT a production cleanup entrypoint.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$FixtureParent,
      [Parameter(Mandatory=$true)][string]$EvidencePath)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'probes\recycle_test_support.ps1')
$source=Join-Path $PSScriptRoot 'probes\workspace_recycle_probe.cs'
$root=$null
try {
    Assert-RecycleProbeHost
    $root=New-RecycleProbeRoot $FixtureParent
    Add-Type -Path $source
    $result=[WorkspaceRecycleProbe.Probe]::Run($root)
    if(-not ($result.VetoPreserved -and $result.PinnedPreserved -and $result.RecycledReceipt -and $result.Restored -and $result.ContentsEqual -and $result.IdentitiesEqual)) { throw 'Synthetic round-trip evidence incomplete' }
    $receipt=[ordered]@{schema=2;utc=[datetime]::UtcNow.ToString('o');status='PASS_SYNTHETIC_ONLY';source_sha256=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash;harness_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash;powershell_version=$PSVersionTable.PSVersion.ToString();apartment=[Threading.Thread]::CurrentThread.ApartmentState.ToString();fixture_temp_root=$root;result=$result;production_recycle_ready=$false;source_attestations=@{real_workspace_operations=0;permanent_delete_fallback=$false;bin_enumeration_or_empty=$false;basis='Source/launcher scope attestations,not measured Shell counters'}}
    Write-RecycleProbeEvidence $receipt $EvidencePath
    $receipt|ConvertTo-Json -Depth 10
} catch {
    $probe='WorkspaceRecycleProbe.Probe'-as[type]
    $fixture=if($probe){$probe::LastFixture}else{$null}
    $receipt=[ordered]@{schema=2;utc=[datetime]::UtcNow.ToString('o');status='FAIL_KEEP_SYNTHETIC_FIXTURES_NO_RETRY';source_sha256=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash;harness_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash;powershell_version=$PSVersionTable.PSVersion.ToString();apartment=[Threading.Thread]::CurrentThread.ApartmentState.ToString();fixture_temp_root=$root;fixture=$fixture;failure=$_.Exception.GetBaseException().Message;production_recycle_ready=$false}
    Write-RecycleProbeEvidence $receipt $EvidencePath
    throw
}
