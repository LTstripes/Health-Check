# Synthetic-only feasibility evidence, NOT a production cleanup entrypoint.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$FixtureParent,
      [Parameter(Mandatory=$true)][string]$EvidencePath)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$source=Join-Path $PSScriptRoot 'probes\workspace_recycle_probe.cs'
Add-Type -Path $source
$result=[WorkspaceRecycleProbe.Probe]::Run($FixtureParent)
if(-not ($result.VetoPreserved -and $result.PinnedPreserved -and $result.RecycledReceipt -and $result.Restored -and $result.ContentsEqual -and $result.IdentitiesEqual)) { throw 'Synthetic round-trip evidence incomplete' }
$receipt=[ordered]@{utc=[datetime]::UtcNow.ToString('o');status='PASS_SYNTHETIC_ONLY';source_sha256=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash;process=$PSVersionTable.PSVersion.ToString();apartment=[Threading.Thread]::CurrentThread.ApartmentState.ToString();result=$result;production_recycle_ready=$false;real_workspace_operations=0;permanent_delete_fallback=$false;bin_enumeration_or_empty=$false}
$receipt|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $EvidencePath -Encoding UTF8
$receipt|ConvertTo-Json -Depth 6
