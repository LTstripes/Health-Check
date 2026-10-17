# Child process for synthetic crash/race/write evidence only; no production hook.
param([Parameter(Mandatory=$true)][string]$Config)
$ErrorActionPreference='Stop'
$c=Get-Content -LiteralPath $Config -Raw|ConvertFrom-Json
if($c.Mode -eq 'Write'){
    [IO.File]::WriteAllText((Join-Path $c.Location 'file.txt'),'external changed contents')
    exit 0
}
if($c.Mode -eq 'NewOldPath'){
    [void][IO.Directory]::CreateDirectory($c.Path)
    [IO.File]::WriteAllText((Join-Path $c.Path 'foreign.txt'),'foreign new root preserved')
    exit 0
}
. (Join-Path $PSScriptRoot '..\scripts\cleanup-workspaces.ps1')
Initialize-JanitorNative
$script:ApprovedRoots=@($c.Client);$script:LogDirectory=$c.Ops;$script:RecoveryDirectory=$c.Recovery;$script:WorkspaceMutexName=$c.Mutex
if($c.Mode -eq 'Resume'){
    try{$r=Invoke-WorkerLifecycle -Action Resume -Workspace $c.Path -Owner synthetic -ClaimId $c.Token; 'RESUMED';exit 0}
    catch{if($_.Exception.Message -eq 'workspace-busy'){'BUSY';exit 91};throw}
}
$realWrite=${function:Write-LifecycleRecord}
$realJournalWrite=${function:Write-RetirementJournal}
function Write-RetirementJournal([string]$Path,$Journal,[switch]$Create){
    & $script:realJournalWrite $Path $Journal -Create:$Create
    if($c.Mode -eq 'CrashBeforeState' -and $Journal.Phase -eq 'prepared'){[Environment]::Exit(87)}
    if($c.Mode -eq 'CrashAfterCancelledJournal' -and $Journal.Phase -eq 'cancelled'){[Environment]::Exit(88)}
}
function Write-LifecycleRecord([string]$Path,$Record,[switch]$Create){
    & $script:realWrite $Path $Record -Create:$Create
    if($c.Mode -eq 'CrashBeforeRename' -and $Record.State -eq 'retiring'){[Environment]::Exit(83)}
    if($c.Mode -eq 'CrashBeforeRestore' -and $Record.State -eq 'restoring'){[Environment]::Exit(85)}
}
if($c.Mode -eq 'CrashAfterRename'){
    function Complete-RetirementInspection {param($Path,$Record,$Journal,$Location) [Environment]::Exit(84)}
}
if($c.Mode -eq 'CrashAfterRestore'){
    function Finish-RetirementReturn {param($Path,$Record,$Journal,$Phase) [Environment]::Exit(86)}
}
if($c.Mode -eq 'CrashAfterCancelledJournal'){
    [void](Invoke-WorkspaceLock {Invoke-RetirementRecovery $c.Path synthetic $c.Token})
}elseif($c.Mode -like '*Restore'){
    [void](Invoke-WorkspaceLock {Invoke-RetirementRecovery $c.Path synthetic $c.Token -Restore})
}else{
    Invoke-WorkspaceLock {
        $r=Get-LifecycleRecord $c.Path
        $tree=New-Object HealthCheck.WorkspaceCleanup.Tree($true)
        try{$tree.Scan($c.Path,25000);[void](Invoke-RetirementMove $c.Path $r $tree)}finally{$tree.Dispose()}
    }
}
exit 0
