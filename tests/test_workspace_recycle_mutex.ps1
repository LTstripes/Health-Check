# Production lifecycle lock + actual synthetic Shell round-trip boundary tests.
# These are coordination primitives, NOT an integrated eligible-workspace recycler.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$FixtureParent,
      [Parameter(Mandatory=$true)][string]$EvidencePath)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'probes\recycle_test_support.ps1')
Assert-RecycleProbeHost
$helper=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\scripts\cleanup-workspaces.ps1'))
$native=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'probes\workspace_recycle_probe.cs'))
. $helper
Initialize-JanitorNative
Add-Type -Path $native
$fixtureRoot=New-RecycleProbeRoot $FixtureParent
$group=Join-Path $fixtureRoot ('workspace-recycle-mutex-'+[guid]::NewGuid().ToString('N'))
if(Test-Path -LiteralPath $group){throw 'Owned mutex fixture collision'}
[void][IO.Directory]::CreateDirectory($group)
$script:ApprovedRoots=@((Join-Path $group 'codex'))
$script:LogDirectory=Join-Path $group 'ops'
[void][IO.Directory]::CreateDirectory($script:ApprovedRoots[0])
[void][IO.Directory]::CreateDirectory($script:LogDirectory)
$script:WorkspaceMutexName='Local\RecycleContract-'+[guid]::NewGuid().ToString('N')
$childSource=@'
param([string]$InputFile)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$inputRecord=Get-Content -LiteralPath $InputFile -Raw|ConvertFrom-Json
. $inputRecord.helper
$script:ApprovedRoots=@($inputRecord.client)
$script:LogDirectory=$inputRecord.ops
$script:WorkspaceMutexName=$inputRecord.mutex
Initialize-JanitorNative
Add-Type -Path $inputRecord.native
$ready=[Threading.EventWaitHandle]::OpenExisting($inputRecord.ready)
$release=[Threading.EventWaitHandle]::OpenExisting($inputRecord.release)
try {
    Invoke-WorkspaceLock {
        if($inputRecord.mode -eq 'resume-first') {
            $claim=Invoke-WorkspaceLifecycle 'Resume' $inputRecord.target 'synthetic-contract' $inputRecord.claim
            $readyRecord=[ordered]@{mode=$inputRecord.mode;resumed=$true;shell_roundtrip=$false}
        } else {
            if($inputRecord.mode -eq 'crash-after-shell') {
                $record=Get-LifecycleRecord $inputRecord.target
                $record.State='deleting'
                Write-LifecycleRecord $inputRecord.target $record
            }
            $probe=[WorkspaceRecycleProbe.Probe]::Run($inputRecord.scratch)
            $readyRecord=[ordered]@{mode=$inputRecord.mode;resumed=$false;shell_roundtrip=($probe.Restored -and $probe.IdentitiesEqual -and $probe.ContentsEqual)}
        }
        $readyRecord|ConvertTo-Json|Set-Content -LiteralPath $inputRecord.response -Encoding UTF8
        [void]$ready.Set()
        if(-not $release.WaitOne(30000)){throw 'Synthetic release timeout'}
        if($inputRecord.mode -eq 'crash-after-shell'){[Environment]::Exit(0)}
    }
} finally {$ready.Dispose();$release.Dispose()}
'@
$childFile=Join-Path $group 'child.ps1'
[IO.File]::WriteAllText($childFile,$childSource,[Text.UTF8Encoding]::new($false))
function GitFixture([string]$Path,[string[]]$Arguments) {
    $r=Invoke-JanitorGit $Path $Arguments
    if($r.Code -ne 0){throw 'Synthetic Git fixture setup failed'}
}
$cases=@()
foreach($mode in @('resume-first','recycle-first','crash-after-shell')) {
    $target=Join-Path $script:ApprovedRoots[0] $mode
    $claim=Invoke-WorkerLifecycle -Action Create -Workspace $target -Owner 'synthetic-contract'
    GitFixture $target @('init','--initial-branch=main')
    GitFixture $target @('remote','add','origin',$script:ExpectedOrigin)
    [IO.File]::WriteAllText((Join-Path $target 'synthetic.txt'),'new synthetic lifecycle fixture')
    GitFixture $target @('add','synthetic.txt')
    GitFixture $target @('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-m','synthetic')
    $claim=Invoke-WorkerLifecycle -Action Bind -Workspace $target -Owner 'synthetic-contract' -ClaimId $claim.Claim
    $claim=Invoke-WorkerLifecycle -Action Complete -Workspace $target -Owner 'synthetic-contract' -ClaimId $claim.Claim
    $nonce=[guid]::NewGuid().ToString('N')
    $readyName='Local\RecycleReady-'+$nonce
    $releaseName='Local\RecycleRelease-'+$nonce
    $ready=[Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset,$readyName)
    $release=[Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset,$releaseName)
    $scratch=New-RecycleProbeRoot $FixtureParent
    $response=Join-Path $group ($mode+'-response.json')
    $inputFile=Join-Path $group ($mode+'-input.json')
    [ordered]@{helper=$helper;native=$native;client=$script:ApprovedRoots[0];ops=$script:LogDirectory;mutex=$script:WorkspaceMutexName;ready=$readyName;release=$releaseName;target=$target;claim=$claim.Claim;mode=$mode;scratch=$scratch;response=$response}|ConvertTo-Json|Set-Content -LiteralPath $inputFile -Encoding UTF8
    $process=$null
    # Keep the named kernel object alive across child exit. Without this observer
    # the last handle may vanish and a later call could create a new mutex.
    $observer=[Threading.Mutex]::new($false,$script:WorkspaceMutexName)
    try {
        $args=@('-NoLogo','-NoProfile','-NonInteractive','-STA','-File',$childFile,'-InputFile',$inputFile)
        $argLine=($args|ForEach-Object {Quote-JanitorArgument $_}) -join ' '
        $process=Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $argLine -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $group ($mode+'-stdout.log')) -RedirectStandardError (Join-Path $group ($mode+'-stderr.log'))
        # Capture this exact child's native handle before releasing its wait.
        # The earlier missing/failed exit observation is retained, not explained away.
        [void]$process.Handle
        if(-not $ready.WaitOne(30000)){throw 'Child ready timeout;retain owned fixture/logs'}
        $child=Get-Content -LiteralPath $response -Raw|ConvertFrom-Json
        $busy=$false
        if($mode -eq 'resume-first') {
            try {Invoke-WorkspaceLock {throw 'Unexpected Shell boundary entry'}} catch {if($_.Exception.Message -ne 'workspace-busy'){throw};$busy=$true}
        } else {
            try {Invoke-WorkerLifecycle -Action Resume -Workspace $target -Owner 'synthetic-contract' -ClaimId $claim.Claim|Out-Null} catch {if($_.Exception.Message -ne 'workspace-busy'){throw};$busy=$true}
        }
        if(-not $busy){throw 'Mutex did not exclude the competing operation'}
        if($mode -ne 'resume-first' -and -not $child.shell_roundtrip){throw 'Actual synthetic Shell boundary missing'}
        [void]$release.Set()
        if(-not $process.WaitForExit(10000)){throw 'Owned child exit timeout'}
        $exitCode=$process.ExitCode
        if($null -eq $exitCode -or $exitCode -ne 0){throw 'Owned child native exit evidence missing or failed'}
        $retired=$false
        $abandoned=$false
        if($mode -eq 'crash-after-shell') {
            $observerHeld=$false
            try {
                try {$observerHeld=$observer.WaitOne(0)} catch [Threading.AbandonedMutexException] {$observerHeld=$true;$abandoned=$true}
                if(-not $observerHeld -or -not $abandoned){throw 'Same-object abandoned mutex acquisition not observed'}
            } finally {if($observerHeld){$observer.ReleaseMutex()}}
            try {Invoke-WorkerLifecycle -Action Resume -Workspace $target -Owner 'synthetic-contract' -ClaimId $claim.Claim|Out-Null} catch {if($_.Exception.Message -ne 'lifecycle-retired'){throw};$retired=$true}
            if(-not $retired){throw 'Abandoned mutex cleared durable retirement'}
        }
        $record=Invoke-WorkspaceLock {Get-LifecycleRecord $target}
        $cases+=[pscustomobject]@{mode=$mode;child_exit_code=$exitCode;competing_operation_rejected_busy=$busy;shell_roundtrip=[bool]$child.shell_roundtrip;state_after=$record.State;observer_handle_retained_across_exit=$true;abandoned_mutex_observed=$abandoned;resume_refused_retired_after_abandonment=$retired;target_still_present=(Test-Path -LiteralPath $target -PathType Container)}
    } finally {
        [void]$release.Set()
        if($null -ne $process){if(-not $process.HasExited -and -not $process.WaitForExit(5000)){$process.Kill();$process.WaitForExit()};$process.Dispose()}
        $observer.Dispose();$ready.Dispose();$release.Dispose()
    }
}
$receipt=[ordered]@{schema=2;utc=[datetime]::UtcNow.ToString('o');status='PASS_COORDINATION_PRIMITIVES_ONLY';harness_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash;helper_sha256=(Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash;probe_sha256=(Get-FileHash -LiteralPath $native -Algorithm SHA256).Hash;fixture_temp_root=$fixtureRoot;fixture_group=$group;cases=$cases;production_ready=$false;source_attestations=@{retention_backdating=$false;network_fetch=$false;basis='Source/launcher attestations,not measured network counters'};limitations='Bound newly completed lifecycle targets coordinate against actual Shell round-trips on separate owned GUID fixtures under the same mutex. This is not integrated eligible-workspace recycle or solved recovery semantics.'}
Write-RecycleProbeEvidence $receipt $EvidencePath
$receipt|ConvertTo-Json -Depth 10
