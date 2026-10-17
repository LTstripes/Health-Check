# Run once: existing eligibility regressions, then real synthetic relocation cases.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'test_cleanup_workspaces.ps1') -FixtureOnly
function Life([string]$Action,[string]$Path,[string]$Token) {Invoke-WorkspaceLock {Invoke-WorkspaceLifecycle $Action $Path synthetic $Token}}
function Claim([string]$Path) {Invoke-WorkspaceLock {Get-LifecycleRecord $Path}}
function Reject([scriptblock]$Action,[string]$Message,[string]$Expected='') {
    $failed=$false;try{& $Action|Out-Null}catch{$failed=$true;if($Expected){Assert ($_.Exception.Message -ceq $Expected) ($Message+': exact rejection')}}
    Assert $failed $Message
}
$script:CaseEvidence=New-Object Collections.Generic.List[object]
function Journal([string]$Path){Invoke-WorkspaceLock {Read-RetirementJournal $Path}}
function RecordCase([string]$Name,[string]$Outcome){$script:CaseEvidence.Add([pscustomobject]@{Name=$Name;Outcome=$Outcome})}
function Child([string]$Mode,[string]$Path,[string]$Token='', [string]$Location=''){
    $cfg=Join-Path $script:Temp ('child-'+[guid]::NewGuid().ToString('N')+'.json')
    [ordered]@{Mode=$Mode;Path=$Path;Token=$Token;Location=$Location;Client=$script:Client;Ops=$script:LogDirectory;Recovery=$script:RecoveryDirectory;Mutex=$script:WorkspaceMutexName}|ConvertTo-Json|Set-Content -LiteralPath $cfg -Encoding UTF8
    $out=$cfg+'.out';$err=$cfg+'.err'
    $worker=Join-Path $PSScriptRoot 'retirement-worker.ps1'
    $args='-NoLogo -NoProfile -NonInteractive -File '+(Quote-JanitorArgument $worker)+' -Config '+(Quote-JanitorArgument $cfg)
    $p=Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
    try{
        $null=$p.Handle
        if(-not $p.WaitForExit(45000)){throw 'synthetic child timeout; retain process/fixtures'}
        $p.Refresh()
        return [pscustomobject]@{Exit=$p.ExitCode;Output=[IO.File]::ReadAllText($out);Error=[IO.File]::ReadAllText($err)}
    }finally{$p.Dispose()}
}
$realComplete=${function:Complete-RetirementInspection};$realWrite=${function:Write-LifecycleRecord}
try{
    $happy=Fixture 'retirement-roundtrip';$old=Claim $happy
    $beforeRoot=[HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($happy)
    $beforeGit=[HealthCheck.WorkspaceCleanup.Tree]::IdentityOf((Join-Path $happy '.git'))
    $r=Check $happy 'recoverably-retired' $true;$j=Journal $happy
    Assert ($r.Result -eq 'RETIRED' -and $j.Phase -eq 'retired' -and $j.BeforeDigest -ceq $j.AfterDigest) 'real eligible transaction retired'
    Assert ([HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($j.Destination) -ceq $beforeRoot) 'root identity bound through move'
    Assert (([IO.File]::ReadAllText((Join-Path $script:LogDirectory $j.AfterObservation))).Contains('NonSnapshot=true')) 'manifest explicitly non-snapshot'
    [void](Check $happy 'retirement-pending' $true)
    Reject {Life Resume $happy $old.Claim} 'retired cannot resume' 'lifecycle-retired'
    $restored=Invoke-WorkspaceLock {Invoke-RetirementRecovery $happy synthetic $old.Claim -Restore}
    Assert ($restored.State -eq 'paused' -and $restored.Generation -eq '2' -and $restored.Claim -ne $old.Claim) 'restore grants new paused claim only'
    Assert ([HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($happy) -ceq $beforeRoot -and [HealthCheck.WorkspaceCleanup.Tree]::IdentityOf((Join-Path $happy '.git')) -ceq $beforeGit) 'root and Git identities restored'
    Reject {Invoke-WorkerLifecycle CheckActive $happy synthetic $restored.Claim} 'restored paused claim cannot write'
    RecordCase 'eligible-roundtrip-double-run' 'RETIRED;SECOND_RUN_PRESERVE;RESTORED_PAUSED_SAME_ROOT_GIT'

    # Attempt root substitution after durable lifecycle write, while root pin remains.
    $swap=Fixture 'retirement-root-swap';$script:SwapBlocked=$false
    function Write-LifecycleRecord([string]$Path,$Record,[switch]$Create){
        & $script:realWrite $Path $Record -Create:$Create
        if($Path -eq $swap -and $Record.State -eq 'retiring'){
            try{[IO.Directory]::Move($Path,($Path+'-stolen'))}catch{$script:SwapBlocked=$true}
        }
    }
    [void](Check $swap 'recoverably-retired' $true);Assert $script:SwapBlocked 'root substitution blocked after intent'
    ${function:Write-LifecycleRecord}=$realWrite
    RecordCase 'root-substitution-after-intent' 'DENIED_BY_RETAINED_ROOT_HANDLE;EXPECTED_ROOT_RETIRED'

    foreach($mode in @('Write','NewOldPath','Junction','Limit')){
        $script:Injection=$mode;$script:InjectionPath=Fixture ('retirement-'+$mode.ToLowerInvariant())
        $r=Claim $script:InjectionPath
        function Complete-RetirementInspection($Path,$Record,$Journal,$Location,$Binding){
            switch($script:Injection){
                'Write' {$c=Child Write $Path '' $Location;Assert ($c.Exit -eq 0) 'external write child completed'}
                'NewOldPath' {$c=Child NewOldPath $Path;Assert ($c.Exit -eq 0) 'external old-path creator completed'}
                'Junction' {[void](New-Item -ItemType Junction -Path (Join-Path $Location 'unapproved-link') -Target $script:OutsideTarget)}
                'Limit' {$script:EntryLimit=1}
            }
            & $script:realComplete $Path $Record $Journal $Location $Binding
        }
        $script:OutsideTarget=Join-Path $script:Temp 'decoy-preserved'
        [void][IO.Directory]::CreateDirectory($script:OutsideTarget)
        [IO.File]::WriteAllText((Join-Path $script:OutsideTarget 'sentinel.txt'),'external target preserved')
        [void](Check $script:InjectionPath 'retirement-needs-review-stop' $true)
        $script:EntryLimit=25000;$j=Journal $script:InjectionPath
        Assert ($j.Phase -eq 'needs_review' -and (Claim $script:InjectionPath).State -eq 'needs_review') 'observed mismatch durable NEEDS_REVIEW'
        Assert ([HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($j.Destination) -ceq $r.RootId) 'same root retained despite descendant/namespace mutation'
        Assert ([IO.File]::ReadAllText((Join-Path $script:OutsideTarget 'sentinel.txt')) -ceq 'external target preserved') 'junction target untouched'
        if($mode -eq 'Write'){Assert ([IO.File]::ReadAllText((Join-Path $j.Destination 'file.txt')) -ceq 'external changed contents') 'external actual contents preserved'}
        if($mode -eq 'NewOldPath'){Assert ([IO.File]::ReadAllText((Join-Path $script:InjectionPath 'foreign.txt')) -ceq 'foreign new root preserved') 'new old-path root preserved'}
        Reject {Invoke-WorkspaceLock {Invoke-RetirementRecovery $script:InjectionPath synthetic $r.Claim -Restore}} 'NEEDS_REVIEW never auto repaired' 'retirement-needs-review'
        RecordCase ('post-rename-'+$mode) 'SAME_ROOT;NEEDS_REVIEW;NO_RETRY_RESTORE_TRAVERSAL_OR_DELETE'
    }
    ${function:Complete-RetirementInspection}=$realComplete

    # Retirement collision introduced at the exact journaled destination.
    $collision=Fixture 'retirement-destination-collision';$c=Claim $collision
    function Write-LifecycleRecord([string]$Path,$Record,[switch]$Create){
        & $script:realWrite $Path $Record -Create:$Create
        if($Path -eq $collision -and $Record.State -eq 'retiring'){
            $j=Read-RetirementJournal $Path;[void][IO.Directory]::CreateDirectory($j.Destination)
            [IO.File]::WriteAllText((Join-Path $j.Destination 'foreign.txt'),'destination preserved')
        }
    }
    [void](Check $collision 'retirement-needs-review-stop' $true);$j=Journal $collision
    Assert ([HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($collision) -ceq $c.RootId) 'no-replace collision preserves source'
    Assert ([IO.File]::ReadAllText((Join-Path $j.Destination 'foreign.txt')) -ceq 'destination preserved') 'no-replace collision preserves destination'
    ${function:Write-LifecycleRecord}=$realWrite
    RecordCase 'retirement-destination-collision' 'BOTH_PRESERVED;NEEDS_REVIEW'

    $rc=Fixture 'retirement-restore-collision';$c=Claim $rc;[void](Check $rc 'recoverably-retired' $true);$j=Journal $rc
    [void][IO.Directory]::CreateDirectory($rc);[IO.File]::WriteAllText((Join-Path $rc 'foreign.txt'),'restore collision preserved')
    $result=Invoke-WorkspaceLock {Invoke-RetirementRecovery $rc synthetic $c.Claim -Restore}
    Assert ($result.State -eq 'NEEDS_REVIEW' -and [IO.File]::ReadAllText((Join-Path $rc 'foreign.txt')) -ceq 'restore collision preserved') 'restore collision refuses replacement'
    Assert ([HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($j.Destination) -ceq $c.RootId) 'recovery root survives restore collision'
    RecordCase 'restore-destination-collision' 'BOTH_PRESERVED;NEEDS_REVIEW'

    foreach($mode in @('CrashBeforeRename','CrashAfterRename','CrashBeforeRestore','CrashAfterRestore')){
        $path=Fixture ('retirement-'+$mode.ToLowerInvariant());$c=Claim $path
        if($mode -like '*Restore'){[void](Check $path 'recoverably-retired' $true)}
        # Keep this exact named kernel mutex alive across child exit (no fake abandonment proof).
        $observer=New-Object Threading.Mutex($false,$script:WorkspaceMutexName)
        try{
            $result=Child $mode $path $c.Claim
            $expected=@{CrashBeforeRename=83;CrashAfterRename=84;CrashBeforeRestore=85;CrashAfterRestore=86}[$mode]
            Assert ($result.Exit -eq $expected) ('intentional crash exit '+$mode)
            $abandoned=$false;$held=$false
            try{try{$held=$observer.WaitOne(0)}catch [Threading.AbandonedMutexException]{$held=$true;$abandoned=$true}}finally{if($held){$observer.ReleaseMutex()}}
            Assert $abandoned 'actual abandoned mutex observed on retained kernel object'
            Reject {Life Resume $path $c.Claim} 'crash does not authorize Resume' 'lifecycle-retired'
            $resolved=Invoke-WorkspaceLock {Invoke-RetirementRecovery $path synthetic $c.Claim}
            switch($mode){
                'CrashBeforeRename' {Assert ($resolved.State -eq 'paused' -and [HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($path) -ceq $c.RootId) 'pre-rename explicit reconcile cancels to paused'}
                'CrashAfterRename' {Assert ($resolved.State -eq 'RETIRED' -and [HealthCheck.WorkspaceCleanup.Tree]::IdentityOf((Journal $path).Destination) -ceq $c.RootId) 'post-rename explicit reconcile does not repeat move'}
                'CrashBeforeRestore' {Assert ($resolved.State -eq 'NEEDS_REVIEW') 'uncertain restore does not retry'}
                'CrashAfterRestore' {Assert ($resolved.State -eq 'paused' -and [HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($path) -ceq $c.RootId) 'post-restore reconcile verifies before paused claim'}
            }
            RecordCase $mode ('EXPECTED_EXIT_'+$expected+';REAL_ABANDONED_MUTEX;EXPLICIT_RECONCILIATION')
        }finally{$observer.Dispose()}
    }

    $race=Fixture 'retirement-resume-race';$c=Claim $race
    $busy=Invoke-WorkspaceLock {Child Resume $race $c.Claim}
    Assert ($busy.Exit -eq 91 -and $busy.Output.Contains('BUSY')) 'cross-process Resume excluded by held retirement mutex'
    $first=Child Resume $race $c.Claim
    Assert ($first.Exit -eq 0) 'cross-process Resume first succeeds'
    [void](Check $race 'lifecycle-not-completed' $true)
    RecordCase 'cross-process-resume-order' 'MUTEX_BUSY_WHILE_HELD;RESUME_FIRST_INVALIDATES_ELIGIBILITY'

    $writeFail=Fixture 'retirement-return-record-failure';$c=Claim $writeFail
    [void](Check $writeFail 'recoverably-retired' $true)
    $script:FailPausedWrite=$true
    function Write-LifecycleRecord([string]$Path,$Record,[switch]$Create){
        if($Path -eq $writeFail -and $Record.State -eq 'paused' -and $script:FailPausedWrite){$script:FailPausedWrite=$false;throw 'synthetic return record write failure'}
        & $script:realWrite $Path $Record -Create:$Create
    }
    $result=Invoke-WorkspaceLock {Invoke-RetirementRecovery $writeFail synthetic $c.Claim -Restore}
    ${function:Write-LifecycleRecord}=$realWrite
    $failedRecord=Claim $writeFail
    Assert ($result.State -eq 'NEEDS_REVIEW' -and $failedRecord.State -eq 'needs_review' -and $failedRecord.Claim -ceq $c.Claim -and $failedRecord.Completed -cne '-') 'failed paused-claim commit retains valid old retirement authority'
    Assert ([HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($writeFail) -ceq $c.RootId) 'failed state commit preserves returned root'
    RecordCase 'restore-final-record-write-failure' 'RETURNED_ROOT_PRESERVED;VALID_NEEDS_REVIEW_WITHOUT_NEW_CLAIM'

    # P1 regression: journal-only intent, then cancellation-journal-only commit.
    $early=Fixture 'retirement-journal-before-state';$c=Claim $early
    $observer=New-Object Threading.Mutex($false,$script:WorkspaceMutexName)
    try{
        foreach($phase in @('CrashBeforeState','CrashAfterCancelledJournal')){
            $child=Child $phase $early $c.Claim
            $expected=if($phase -eq 'CrashBeforeState'){87}else{88}
            Assert ($child.Exit -eq $expected) 'exact early crash exit'
            $held=$false;$abandoned=$false
            try{try{$held=$observer.WaitOne(0)}catch [Threading.AbandonedMutexException]{$held=$true;$abandoned=$true}}finally{if($held){$observer.ReleaseMutex()}}
            Assert $abandoned 'early journal crash abandoned same retained mutex'
            Assert ((Claim $early).Format -eq '1' -and (Claim $early).State -eq 'completed') 'early crash retains old completed record for negative test'
            Reject {Life Resume $early $c.Claim} 'pending or incomplete closed handoff cannot Resume' 'retirement-pending'
            $fetches=@($script:Calls|Where-Object {$_.Args[0] -eq 'fetch'}).Count
            [void](Check $early 'retirement-pending' $true)
            Assert (@($script:Calls|Where-Object {$_.Args[0] -eq 'fetch'}).Count -eq $fetches) 'incomplete closed handoff cannot fetch or auto-retire'
            Assert ([HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($early) -ceq $c.RootId) 'early crash root never moved'
        }
        $priorTransaction=(Journal $early).Transaction
        $fixed=Invoke-WorkspaceLock {Invoke-RetirementRecovery $early synthetic $c.Claim}
        Assert ($fixed.State -eq 'paused' -and $fixed.Claim -ne $c.Claim) 'explicit reconciliation finishes cancelled handoff'
        $next=Life Resume $early $fixed.Claim
        Assert ($next.State -eq 'active' -and $next.Generation -eq '3') 'committed handoff permits legitimate later Resume'
        [void](Life Complete $early $next.Claim);Old $early
        [void](Check $early 'recoverably-retired' $true)
        Assert ([IO.File]::Exists((Join-Path $script:LogDirectory ('workspace-retirement-history-'+$priorTransaction+'.state')))) 'new completion cycle preserves previous closed journal history'
        RecordCase 'journal-only-and-cancelled-only-crashes' 'OLD_COMPLETED_CANNOT_AUTO_RETRY;EXPLICIT_RECOVER_PAUSED;NEW_COMPLETION_CYCLE_ALLOWED'
    }finally{$observer.Dispose()}

    # P2 regression: binding exists BEFORE the first descendant enumeration.
    $pinPath=Fixture 'retirement-inspection-root-binding';$c=Claim $pinPath
    $binding=New-Object HealthCheck.WorkspaceCleanup.Tree($true);$observation=New-Object HealthCheck.WorkspaceCleanup.Tree($false)
    try{
        $binding.BindRootOnly($pinPath,$c.RootId)
        Reject {[IO.Directory]::Move($pinPath,($pinPath+'-replaced'))} 'root-only inspection binding blocks root swap before enumeration'
        Reject {$observation.ObserveBound($null,$pinPath,$c.RootId,25000)} 'unbound observation rejected before enumeration'
        $observation.ObserveBound($binding,$pinPath,$c.RootId,25000)
        Assert ($observation.Entries.Count -gt 1) 'bound inspection enumerates expected descendants'
    }finally{$observation.Dispose();$binding.Dispose()}
    $wrong=New-Object HealthCheck.WorkspaceCleanup.Tree($true)
    try{Reject {$wrong.BindRootOnly($pinPath,$old.RootId)} 'different root identity rejected before inspection'}finally{$wrong.Dispose()}
    $parked=$pinPath+'-parked';[IO.Directory]::Move($pinPath,$parked)
    [void](New-Item -ItemType Junction -Path $pinPath -Target $script:OutsideTarget)
    $j=[ordered]@{Transaction=[guid]::NewGuid().ToString('N');RootId=$c.RootId;BeforeDigest=('0'*64);GitId=$c.GitId;Path=$c.Path;Enrollment=$c.Enrollment}
    $inspected=Invoke-WorkspaceLock {Get-RetirementInspection $pinPath $j}
    Assert (-not $inspected.Good -and $inspected.Digest -eq '-') 'replaced junction root rejected before manifest traversal'
    Assert ([IO.File]::ReadAllText((Join-Path $script:OutsideTarget 'sentinel.txt')) -ceq 'external target preserved') 'inspection never touches junction target data'
    RecordCase 'explicit-inspection-root-binding' 'PRE_ENUMERATION_SWAP_DENIED;UNBOUND_WRONG_ID_AND_JUNCTION_ROOT_REJECTED'

    $evidence=[ordered]@{Status='PASS_SYNTHETIC_RELOCATION_ONLY';Utc=[datetime]::UtcNow.ToString('o');Assertions=$script:Assertions;FixtureRoot=$script:Temp;Cases=$script:CaseEvidence.ToArray();NonSnapshot=$true;RealWorkspaceMoves=0;PermanentDeleteOrPurge=$false;SourceSha256=(Get-FileHash (Join-Path $PSScriptRoot '..\scripts\cleanup-workspaces.ps1')).Hash;NativeSha256=(Get-FileHash (Join-Path $PSScriptRoot '..\scripts\cleanup-workspaces.fs.cs')).Hash}|ConvertTo-Json -Depth 6
    $evidence|Set-Content -LiteralPath (Join-Path $script:Temp 'retirement-evidence.json') -Encoding UTF8
    if($env:RETIREMENT_EVIDENCE_DIR){
        [void][IO.Directory]::CreateDirectory($env:RETIREMENT_EVIDENCE_DIR)
        $evidence|Set-Content -LiteralPath (Join-Path $env:RETIREMENT_EVIDENCE_DIR 'retirement-evidence.json') -Encoding UTF8
    }
    'PASS retirement: '+$script:CaseEvidence.Count+' cases, '+$script:Assertions+' assertions; evidence '+(Join-Path $script:Temp 'retirement-evidence.json')
}finally{
    ${function:Complete-RetirementInspection}=$realComplete;${function:Write-LifecycleRecord}=$realWrite
    'Fixtures retained: '+$script:Temp
}
