# Self-contained Windows PowerShell 5.1 synthetic regression; no Owner roots/data.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$taskOwner='synthetic-worker' # Task input supplied BEFORE dot-sourcing the accepted helper.
. (Join-Path $PSScriptRoot '..\scripts\cleanup-workspaces.ps1')
Initialize-JanitorNative
$script:RealGit = ${function:Invoke-JanitorGit}
$script:RemoteFor = @{}
$script:FailFetch=@{}
$script:Calls = New-Object Collections.Generic.List[object]
$script:CimFails = $false
$script:CimRows = @()
function Invoke-JanitorGit([string]$Path, [string[]]$Arguments) {
    $script:Calls.Add([pscustomobject]@{ Path=$Path; Args=$Arguments.Clone() })
    if ($Arguments[0] -eq 'fetch') {
        if ($script:FailFetch.ContainsKey($Path)) { return [pscustomobject]@{ Code=128; Text='' } }
        if (-not $script:RemoteFor.ContainsKey($Path)) { throw 'fixture-fetch-unknown' }
        $Arguments = @($Arguments)
        $Arguments[4] = $script:RemoteFor[$Path]
    }
    return & $script:RealGit $Path $Arguments
}
# Mock only the CIM boundary so every check exercises production process visibility.
function Get-CimInstance {
    [CmdletBinding()]
    param([string]$ClassName)
    if ($ClassName -ne 'Win32_Process') { throw 'unexpected-cim-query' }
    if ($script:CimFails) { throw 'synthetic-cim-query-failure' }
    return $script:CimRows
}
function Assert($Condition, [string]$Message) { if (-not $Condition) { throw "FAIL: $Message" }; $script:Assertions++ }
function Git([string]$Path, [string[]]$Arguments) {
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=(Get-Command git.exe -CommandType Application | Select-Object -First 1).Source
    $start.Arguments=(@('-c', "safe.directory=$Path", '-C', $Path) + $Arguments | ForEach-Object { Quote-JanitorArgument $_ }) -join ' '
    $start.UseShellExecute=$false; $start.CreateNoWindow=$true
    $start.RedirectStandardOutput=$true; $start.RedirectStandardError=$true
    $process=New-Object Diagnostics.Process; $process.StartInfo=$start
    try {
        [void]$process.Start()
        $stdout=$process.StandardOutput.ReadToEndAsync(); $stderr=$process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw ('fixture git failed: ' + $Arguments[0]) }
        return $stdout.GetAwaiter().GetResult().TrimEnd("`r", "`n")
    } finally { $process.Dispose() }
}
function Old([string]$Path) {
    $time = [datetime]::UtcNow.AddDays(-12)
    $entries = @(Get-ChildItem -LiteralPath $Path -Force -Recurse) | Sort-Object { $_.FullName.Length } -Descending
    foreach ($entry in $entries) { $attributes=$entry.Attributes; if (-not $entry.PSIsContainer) { $entry.Attributes=$attributes -band (-bnot [IO.FileAttributes]::ReadOnly) }; $entry.LastWriteTimeUtc=$time; $entry.Attributes=$attributes }
    [IO.Directory]::SetLastWriteTimeUtc($Path, $time)
    # Synthetic time travel only, never a production CLI option. Existing tests
    # manufacture an explicitly completed old snapshot, then probe other guards.
    if ([IO.File]::Exists((Get-LifecycleFile $Path))) {
        Invoke-WorkspaceLock {
            $r=Get-LifecycleRecord $Path
            if ($r.State -eq 'completed') {
                $r.Head=Get-JanitorGitText $Path @('rev-parse','HEAD')
                $r.Completed=$time.Ticks.ToString()
                Write-LifecycleRecord $Path $r
            }
        }
    }
}
function Commit([string]$Path, [string]$Value) {
    [IO.File]::WriteAllText((Join-Path $Path 'file.txt'), $Value)
    [void](Git $Path @('add','file.txt'))
    [void](Git $Path @('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-m','synthetic'))
}
function Fixture([string]$Name) {
    $repo = Join-Path $script:Client $Name
    $claim=Invoke-WorkspaceLock { Invoke-WorkspaceLifecycle 'Create' $repo 'synthetic' '' }
    [void](Git $script:Temp @('clone','--no-hardlinks','--quiet',$script:Remote,$repo))
    [void](Git $repo @('remote','set-url','origin',$script:ExpectedOrigin))
    $script:RemoteFor[$repo]=$script:Remote
    [void](Invoke-WorkspaceLock { Invoke-WorkspaceLifecycle 'Bind' $repo 'synthetic' $claim.Claim })
    [void](Invoke-WorkspaceLock { Invoke-WorkspaceLifecycle 'Complete' $repo 'synthetic' $claim.Claim })
    Old $repo
    return $repo
}
function Check([string]$Path, [string]$Reason, [bool]$Delete=$false) {
    $out = @(Invoke-WorkspaceLock { Invoke-JanitorTask $Path 7 $Delete ([datetime]::UtcNow) })
    $record=$out[-1]
    Assert ($record.Reason -eq $Reason) ("$([IO.Path]::GetFileName($Path)): expected $Reason, got $($record.Reason)")
    return $record
}
$script:Assertions=0
$script:Temp = Join-Path ([IO.Path]::GetTempPath()) ('healthcheck-janitor-' + [guid]::NewGuid().ToString('N'))
$script:Client = Join-Path $script:Temp 'codex'
$script:Remote = Join-Path $script:Temp 'remote.git'
$script:LogDirectory = Join-Path $script:Temp 'ops'
[void][IO.Directory]::CreateDirectory($script:Client)
[void][IO.Directory]::CreateDirectory($script:LogDirectory)
$junction=$null
try {
    # Production policy hard rejects canonical roles, arbitrary roots and nested children.
    foreach ($root in @('D:\HealthCheck\main','D:\HealthCheck\stable','D:\HealthCheck\uat','D:\HealthCheck\ops',
        'C:\arbitrary','D:\HealthCheck\workspaces\codex\nested','D:\HealthCheck\workspaces\codex\..\stable')) {
        $rejected=$false; try { [void](Assert-JanitorRoot $root) } catch { $rejected=$true }
        Assert $rejected 'production root boundary'
    }
    $rejected=$false; try { [void](Invoke-WorkspaceJanitor @('D:\HealthCheck\workspaces\codex') 6) } catch { $rejected=$true }
    Assert $rejected 'retention cannot be less than seven days'
    # Test-only in-memory policy injection. No CLI/env switch in the shipped script.
    $script:ApprovedRoots=@($script:Client)
    $script:WorkspaceMutexName='Local\WorkspaceFixture-' + [guid]::NewGuid().ToString('N')
    $env:GIT_AUTHOR_DATE = [datetime]::UtcNow.AddDays(-12).ToString('o')
    $env:GIT_COMMITTER_DATE=$env:GIT_AUTHOR_DATE
    [void](Git $script:Temp @('init','--bare','--initial-branch=main',$script:Remote))
    $seed = Join-Path $script:Temp 'seed'
    [void](Git $script:Temp @('init','--initial-branch=main',$seed))
    [IO.File]::WriteAllText((Join-Path $seed '.gitignore'), "*.db`n*.token`n*.key`n*.zip`nruntime/`n.env`n.venv/`n.pytest_cache/`n.ruff_cache/`n__pycache__/`n*.py[cod]`n")
    [void](Git $seed @('add','.gitignore'))
    Commit $seed 'base'
    [void](Git $seed @('push',$script:Remote,'main'))

    $script:CimRows=@(
        [pscustomobject]@{ ProcessId=123; CommandLine=$null },
        [pscustomobject]@{ ProcessId=124; CommandLine='  ' },
        [pscustomobject]@{ ProcessId=125 },
        [pscustomobject]@{ ProcessId=126; CommandLine='SYNTHETIC_UNRELATED_COMMAND --private-argument' }
    )
    $clean=Fixture 'clean-merged'
    $record=Check $clean 'clean-published-inactive'
    Assert ($record.Result -eq 'ELIGIBLE') 'old merged eligible despite unrelated unavailable command lines'
    Assert ($record.HiddenProcessCommandLines -eq 3) 'only blank or unavailable commands counted'
    Assert (($record | ConvertTo-Json) -notmatch 'SYNTHETIC_UNRELATED_COMMAND|private-argument|"Commands"|ProcessId') 'task report contains no process commands or identifiers'
    $script:CimRows=@([pscustomobject]@{ CommandLine=$null }) * 65536
    Assert ((Get-JanitorProcesses).HiddenProcessCommandLines -eq 65535) 'hidden command diagnostic count is bounded'
    $script:CimRows=@()
    Assert ([IO.Directory]::Exists($clean)) 'dry-run never deletes'
    # Fetch bookkeeping must not make a later dry-run age young.
    Old $clean
    Assert ($script:Calls.Exists([Predicate[object]]{ param($c) $c.Args[0] -eq 'fetch' -and $c.Args -contains 'origin' })) 'fresh origin fetch requested'

    # Exact source photo directory is code; a runtime marker under it still preserves.
    $sourceEntries=@([pscustomobject]@{ Path=(Join-Path $clean 'src\healthcheck\ingestion\photo'); Directory=$true })
    Test-JanitorMarkers $sourceEntries $clean
    Assert $true 'known tracked photo source directory is not a runtime profile'
    $failed=$false
    try { Test-JanitorMarkers @([pscustomobject]@{ Path=(Join-Path $clean 'src\healthcheck\ingestion\photo\owner.db'); Directory=$false }) $clean } catch { $failed=$true }
    Assert $failed 'source-directory allowance never bypasses private files'
    $dirty=Fixture 'dirty'
    [IO.File]::WriteAllText((Join-Path $dirty 'file.txt'),'modified')
    [void](Check $dirty 'dirty-or-untracked')
    $untracked=Fixture 'untracked'
    [IO.File]::WriteAllText((Join-Path $untracked 'new.txt'),'new')
    [void](Check $untracked 'dirty-or-untracked')
    $unique=Fixture 'unique'
    Commit $unique 'unique-work'
    Old $unique
    [void](Check $unique 'unique-head-commit')
    $ref=Fixture 'unique-ref'
    [void](Git $ref @('switch','-c','unpublished'))
    Commit $ref 'unique-branch'
    [void](Git $ref @('switch','main'))
    Old $ref
    [void](Check $ref 'unique-local-ref')
    $stash=Fixture 'unique-stash'
    [IO.File]::WriteAllText((Join-Path $stash 'file.txt'),'stash-work')
    [void](Git $stash @('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','stash','push'))
    Old $stash
    [void](Check $stash 'unique-local-ref')
    $young=Fixture 'young'
    [IO.File]::SetLastWriteTimeUtc((Join-Path $young 'file.txt'),[datetime]::UtcNow)
    [void](Check $young 'younger-than-retention')
    $boundary=Fixture 'retention-boundary'
    [IO.File]::SetLastWriteTimeUtc((Join-Path $boundary 'file.txt'),[datetime]::UtcNow.AddDays(-7).AddMinutes(1))
    $record=Check $boundary 'younger-than-retention'
    Assert ($record.AgeDays -eq 7) 'rounded display cannot weaken exact seven-day minimum'
    $unavailable=Fixture 'fetch-unavailable'
    $script:FailFetch[$unavailable]=$true
    [void](Check $unavailable 'git-check-failed' $true)
    Assert ([IO.Directory]::Exists($unavailable)) 'unavailable fresh remote preserves workspace'
    $wrong=Fixture 'wrong-repo'
    [void](Git $wrong @('remote','set-url','origin','https://example.invalid/wrong.git'))
    [void](Check $wrong 'wrong-origin')
    $rewrite=Fixture 'rewritten-origin'
    [void](Git $rewrite @('config','url.https://example.invalid/.insteadOf','https://github.com/'))
    [void](Check $rewrite 'remote-rewrite-or-unknown' $true)
    foreach ($marker in @('owner.db','private.token','owner.key','backup.zip','.env','runtime')) {
        $private=Fixture ('marker-' + $marker.Replace('.','-'))
        if ($marker -eq 'runtime') { [void][IO.Directory]::CreateDirectory((Join-Path $private $marker)) }
        else { [IO.File]::WriteAllText((Join-Path $private $marker),'SECRET_HEALTH_VALUE') }
        $record=Check $private 'private-runtime-marker'
        Assert (($record | ConvertTo-Json) -notmatch 'SECRET_HEALTH_VALUE|owner\.db|private\.token') 'marker detail never logged'
    }
    $active=Fixture 'active'
    foreach ($visiblePath in @($active, $active.Replace('\','/'))) {
        $script:CimRows=@(
            [pscustomobject]@{ ProcessId=123; CommandLine=$null },
            [pscustomobject]@{ ProcessId=124; CommandLine="synthetic --cwd $visiblePath" }
        )
        $record=Check $active 'active-process'
        Assert ($record.HiddenProcessCommandLines -eq 1) 'visible match still blocks with unrelated hidden command'
    }
    $script:CimFails=$true
    $record=Check $active 'process-state-unknown'
    Assert ($null -eq $record.HiddenProcessCommandLines) 'failed CIM query never claims a known hidden count'
    Assert ([IO.Directory]::Exists($active)) 'failed CIM query preserves workspace'
    $script:CimFails=$false
    $script:CimRows=@()
    $outside=Join-Path $script:Temp 'outside'
    [void][IO.Directory]::CreateDirectory($outside)
    $junction=Join-Path $script:Client 'junction'
    [void](New-Item -ItemType Junction -Path $junction -Target $outside)
    [void](Check $junction 'filesystem-or-check-unknown' $true)
    Assert ([IO.Directory]::Exists($outside)) 'junction target survives'
    (Get-Item -LiteralPath $junction -Force).Delete()
    $junction=$null
    $nested=Join-Path $clean 'nested'
    [void](Check $nested 'root-rejected' $true)
    Assert ([IO.Directory]::Exists($clean)) 'nested request preserves parent'
    $link=Fixture 'nested-link'
    $junction=Join-Path $link 'outside-link'
    [void](New-Item -ItemType Junction -Path $junction -Target $outside)
    [void](Check $link 'filesystem-or-check-unknown' $true)
    (Get-Item -LiteralPath $junction -Force).Delete()
    $junction=$null
    $hard=Fixture 'hardlink'
    [void](New-Item -ItemType HardLink -Path (Join-Path $hard 'hard.txt') -Target (Join-Path $seed 'file.txt'))
    [void](Check $hard 'filesystem-or-check-unknown' $true)
    Assert ([IO.File]::Exists((Join-Path $seed 'file.txt'))) 'hardlink source survives'
    $external=Fixture 'external-metadata'
    # Do not open referenced external metadata, even if it is another valid Git repo.
    $oldgit=Join-Path $external '.git'
    $savedgit=Join-Path $script:Temp 'saved-external-git'
    Move-Item -LiteralPath $oldgit -Destination $savedgit
    [IO.File]::WriteAllText($oldgit, "gitdir: $seed\.git")
    $beforeCalls=$script:Calls.Count
    [void](Check $external 'external-git-metadata' $true)
    Assert ($script:Calls.Count -eq $beforeCalls) 'external git metadata rejected before invoking Git'
    $unknown=Fixture 'unknown-ignored'
    [IO.File]::WriteAllText((Join-Path $unknown '.gitignore'),'opaque.bin')
    [void](Git $unknown @('add','.gitignore'))
    [void](Git $unknown @('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-m','ignore'))
    [IO.File]::WriteAllText((Join-Path $unknown 'opaque.bin'),'SECRET_HEALTH_VALUE')
    [void](Check $unknown 'unknown-ignored-material')

    # Equivalent patches are accepted only when original raw local refs are published too.
    $equivalent=Fixture 'equivalent'
    [void](Git $equivalent @('switch','-c','published-patch'))
    Commit $equivalent 'same-patch'
    [void](Git $equivalent @('push',$script:Remote,'published-patch'))
    # Different commit message proves patch equivalence, not identical SHA ancestry.
    [IO.File]::WriteAllText((Join-Path $seed 'file.txt'),'same-patch')
    [void](Git $seed @('add','file.txt'))
    [void](Git $seed @('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-m','equivalent main patch'))
    Assert ((Git $seed @('rev-parse','HEAD')) -ne (Git $equivalent @('rev-parse','HEAD'))) 'equivalent fixture has distinct commits'
    [void](Git $seed @('push',$script:Remote,'main'))
    Old $equivalent
    [void](Check $equivalent 'clean-published-inactive')
    Assert ((Git $equivalent @('cherry', 'origin/main', 'HEAD')) -match '^- ') 'equivalent fixture exercises git cherry fallback'

    $applyFixture=Fixture 'apply-clone'
    [void](Check $applyFixture 'removed' $true)
    Assert (-not [IO.Directory]::Exists($applyFixture)) 'Apply removes eligible clone'
    # Realistic generated caches: normal dependency assets and a uv-style hardlink.
    $cacheFixture=Fixture 'generated-cache-apply'
    $package=Join-Path $cacheFixture '.venv\Lib\site-packages\synthetic_package\data'
    [void][IO.Directory]::CreateDirectory($package)
    [IO.File]::WriteAllText((Join-Path $package 'cacert.pem'),'synthetic public CA asset')
    [IO.File]::WriteAllBytes((Join-Path $package 'package.png'),[Convert]::FromBase64String('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5x8AAAAASUVORK5CYII='))
    foreach ($dir in @('.pytest_cache\v\cache','.ruff_cache\version','src\__pycache__')) {
        [void][IO.Directory]::CreateDirectory((Join-Path $cacheFixture $dir))
    }
    [IO.File]::WriteAllText((Join-Path $cacheFixture '.pytest_cache\v\cache\nodeids'),'synthetic cache')
    [IO.File]::WriteAllText((Join-Path $cacheFixture '.ruff_cache\version\cache.bin'),'synthetic cache')
    [IO.File]::WriteAllText((Join-Path $cacheFixture 'src\__pycache__\module.pyc'),'synthetic bytecode')
    [IO.File]::WriteAllText((Join-Path $cacheFixture 'loose.pyo'),'synthetic bytecode')
    $cacheTarget=Join-Path $script:Temp 'shared-dependency.bin'
    [IO.File]::WriteAllText($cacheTarget,'synthetic shared dependency')
    $cacheLink=Join-Path $package 'shared.bin'
    [void](New-Item -ItemType HardLink -Path $cacheLink -Target $cacheTarget)
    Old $cacheFixture
    $scan=New-Object HealthCheck.WorkspaceCleanup.Tree($false)
    try {
        $scan.Scan($cacheFixture,$script:EntryLimit)
        $cacheEntry=$scan.Entries | Where-Object { $_.Path -eq $cacheLink }
        Assert ($cacheEntry.Links -eq 2 -and -not $cacheEntry.GeneratedCache) 'hardlink is provisional until Git cache proof'
    } finally { $scan.Dispose() }
    $record=Check $cacheFixture 'clean-published-inactive'
    Assert ($record.Result -eq 'ELIGIBLE' -and [IO.File]::Exists($cacheLink)) 'realistic cache eligible and dry-run preserves'
    Old $cacheFixture
    # Readonly dependency hardlinks must be unlinked without changing shared attributes.
    [IO.File]::SetAttributes($cacheTarget, [IO.File]::GetAttributes($cacheTarget) -bor [IO.FileAttributes]::ReadOnly)
    $targetHash=(Get-FileHash -LiteralPath $cacheTarget).Hash
    $targetBefore=Get-Item -LiteralPath $cacheTarget
    $targetAttributes=$targetBefore.Attributes; $targetWritten=$targetBefore.LastWriteTimeUtc; $targetLength=$targetBefore.Length
    [void](Check $cacheFixture 'removed' $true)
    Assert (-not [IO.Directory]::Exists($cacheFixture)) 'Apply removes workspace including generated cache'
    Assert ([IO.File]::Exists($cacheTarget) -and (Get-FileHash -LiteralPath $cacheTarget).Hash -eq $targetHash) 'external hardlink target survives with identical contents'
    $targetAfter=Get-Item -LiteralPath $cacheTarget
    Assert ($targetAfter.Attributes -eq $targetAttributes -and $targetAfter.LastWriteTimeUtc -eq $targetWritten -and $targetAfter.Length -eq $targetLength) 'external hardlink target metadata unchanged'
    $unignoredCache=Fixture 'cache-not-ignored'
    [void](Git $unignoredCache @('config','core.excludesFile','NUL'))
    [IO.File]::WriteAllText((Join-Path $unignoredCache '.gitignore'),'')
    [void][IO.Directory]::CreateDirectory((Join-Path $unignoredCache '.venv'))
    [IO.File]::WriteAllText((Join-Path $unignoredCache '.venv\cacert.pem'),'synthetic CA')
    [void](Check $unignoredCache 'generated-cache-unproven' $true)
    $trackedCache=Fixture 'cache-tracked'
    [void][IO.Directory]::CreateDirectory((Join-Path $trackedCache '.venv'))
    [IO.File]::WriteAllText((Join-Path $trackedCache '.venv\cacert.pem'),'synthetic CA')
    [void](Git $trackedCache @('add','--force','.venv/cacert.pem'))
    [void](Check $trackedCache 'generated-cache-unproven' $true)
    $cacheJunction=Fixture 'cache-junction'
    $junction=Join-Path $cacheJunction '.venv'
    [void](New-Item -ItemType Junction -Path $junction -Target $outside)
    [void](Check $cacheJunction 'filesystem-or-check-unknown' $true)
    Assert ([IO.Directory]::Exists($outside)) 'generated-cache junction target survives'
    (Get-Item -LiteralPath $junction -Force).Delete(); $junction=$null
    $privateInCache=Fixture 'cache-private-marker'
    [void][IO.Directory]::CreateDirectory((Join-Path $privateInCache '.venv'))
    [IO.File]::WriteAllText((Join-Path $privateInCache '.venv\owner.db'),'SECRET_HEALTH_VALUE')
    [void](Check $privateInCache 'private-runtime-marker' $true)
    $lookalike=Fixture 'cache-lookalike'
    [void][IO.Directory]::CreateDirectory((Join-Path $lookalike '.venv-other'))
    [void](New-Item -ItemType HardLink -Path (Join-Path $lookalike '.venv-other\shared.bin') -Target $cacheTarget)
    [void](Check $lookalike 'filesystem-or-check-unknown' $true)
    Assert ([IO.File]::Exists($cacheTarget)) 'lookalike cache hardlink remains protected'
    $owner=Fixture 'worktree-owner'
    $worktree=Join-Path $script:Client 'linked-worktree'
    [void](Git $owner @('worktree','add','--detach',$worktree,'HEAD'))
    $script:RemoteFor[$worktree]=$script:Remote
    Old $owner; Old $worktree
    [void](Check $owner 'dependent-worktrees' $true)
    $beforeFetch=@($script:Calls | Where-Object { $_.Args[0] -eq 'fetch' }).Count
    [void](Check $worktree 'shared-worktree-preserved' $true)
    Assert ([IO.Directory]::Exists($worktree)) 'linked worktree preserved'
    Assert (@($script:Calls | Where-Object { $_.Args[0] -eq 'fetch' }).Count -eq $beforeFetch) 'unknown/active shared cohort not fetched'
    Assert ((Git $owner @('worktree','list','--porcelain')) -match 'linked-worktree') 'registration preserved'
    $locked=Join-Path $script:Client 'locked-worktree'
    [void](Git $owner @('worktree','add','--detach',$locked,'HEAD'))
    [void](Git $owner @('worktree','lock',$locked))
    $script:RemoteFor[$locked]=$script:Remote
    Old $owner; Old $locked
    [void](Check $locked 'shared-worktree-preserved' $true)
    Assert ([IO.Directory]::Exists($locked)) 'locked worktree preserved without removal'
    [void](Git $owner @('worktree','unlock',$locked))
    # Lifecycle regressions use production operations and the same project mutex.
    function Life([string]$Action,[string]$Path,[string]$Token) {
        Invoke-WorkspaceLock { Invoke-WorkspaceLifecycle $Action $Path 'synthetic' $Token }
    }
    function Claim([string]$Path) { Invoke-WorkspaceLock { Get-LifecycleRecord $Path } }
    function Reject([scriptblock]$Action,[string]$Message,[string]$Expected='') {
        $failed=$false; try { & $Action | Out-Null } catch { $failed=$true; if ($Expected) { Assert ($_.Exception.Message -ceq $Expected) ($Message + ': exact rejection') } }
        Assert $failed $Message
    }
    function NoFetch([string]$Path,[string]$Reason) {
        $n=@($script:Calls | Where-Object { $_.Args[0] -eq 'fetch' }).Count
        [void](Check $Path $Reason $true)
        Assert (@($script:Calls | Where-Object { $_.Args[0] -eq 'fetch' }).Count -eq $n) 'unproven lifecycle cannot fetch'
        Assert ([IO.Directory]::Exists($Path)) 'unproven lifecycle cannot delete'
    }
    $lifecycle=Fixture 'lifecycle-resume'
    $r=Claim $lifecycle
    Reject { Life 'Complete' $lifecycle ('0'*32) } 'wrong ClaimId cannot complete'
    Reject { Invoke-WorkspaceLock { Invoke-WorkspaceLifecycle 'Resume' $lifecycle 'other-owner' $r.Claim } } 'wrong owner cannot resume'
    $resumed=Life 'Resume' $lifecycle $r.Claim
    Assert ($resumed.Generation -eq '2' -and $resumed.Claim -ne $r.Claim -and $resumed.State -eq 'active') 'Resume-first invalidates completion and claim'
    Reject { Life 'Complete' $lifecycle $r.Claim } 'stale generation ClaimId cannot complete'
    NoFetch $lifecycle 'lifecycle-not-completed'
    [void](Life 'Pause' $lifecycle $resumed.Claim)
    NoFetch $lifecycle 'lifecycle-not-completed'
    Reject { Life 'Complete' $lifecycle $resumed.Claim } 'paused cannot complete without resume'
    Reject { Life 'Create' $lifecycle '' } 'Create cannot adopt a completed/paused existing path'
    $resumed=Life 'Resume' $lifecycle $resumed.Claim
    [void](Life 'Complete' $lifecycle $resumed.Claim)
    [void](Check $lifecycle 'younger-than-retention' $true)
    Old $lifecycle
    [void](Check $lifecycle 'clean-published-inactive')
    # No helper lock, even direct internal entry point, never grants deletion.
    Reject { Invoke-JanitorTask $lifecycle 7 $true ([datetime]::UtcNow) } 'unlocked internal janitor rejected'
    $changed=Fixture 'completed-head-changed'
    Commit $changed 'new-head-after-completion'
    NoFetch $changed 'lifecycle-head-changed'
    $malformed=Fixture 'malformed-claim'
    $claimFile=Get-LifecycleFile $malformed
    $valid=[HealthCheck.WorkspaceCleanup.Tree]::ReadState($claimFile)
    foreach ($bad in @($valid.Replace('Format=1','Format=2'), ($valid+"State=completed`n"), $valid.Replace('State=completed','State=released'), $valid.Replace('Generation=1','Generation=0'), $valid.Replace('Completed=','Unknown='))) {
        [HealthCheck.WorkspaceCleanup.Tree]::WriteState($claimFile,$bad,$false)
        NoFetch $malformed 'lifecycle-invalid'
    }
    [HealthCheck.WorkspaceCleanup.Tree]::WriteState($claimFile,$valid,$false)
    $marker=Join-Path $malformed '.git\workspace-enrollment.state'
    $savedMarker=[HealthCheck.WorkspaceCleanup.Tree]::ReadState($marker)
    [HealthCheck.WorkspaceCleanup.Tree]::WriteState($marker,($savedMarker+"State=completed`n"),$false)
    NoFetch $malformed 'lifecycle-invalid'
    [HealthCheck.WorkspaceCleanup.Tree]::WriteState($marker,$savedMarker,$false)
    $copied=Fixture 'copied-marker'
    [HealthCheck.WorkspaceCleanup.Tree]::WriteState((Join-Path $copied '.git\workspace-enrollment.state'),$savedMarker,$false)
    NoFetch $copied 'lifecycle-identity-changed'
    $legacy=Fixture 'legacy-released'
    [IO.File]::WriteAllText((Join-Path $legacy '.git\codex-owner.json'),'{"owner":"old","status":"released"}')
    NoFetch $legacy 'lifecycle-legacy-metadata'
    $legacyDirectory=Fixture 'legacy-directory-marker'
    [void][IO.Directory]::CreateDirectory((Join-Path $legacyDirectory '.git\codex-owner.json'))
    NoFetch $legacyDirectory 'lifecycle-legacy-metadata'
    $canonicalClient=$script:Client
    try { $script:Client=$script:Client.ToLowerInvariant(); $case=Fixture 'case-normalized' }
    finally { $script:Client=$canonicalClient }
    $caseCanonical=Join-Path $canonicalClient 'case-normalized'
    [void](Check $caseCanonical 'clean-published-inactive')
    Assert ((Claim $case).Path -ceq (Claim $caseCanonical).Path) 'case variants bind one physical enrollment and sweep'
    $loose=Fixture 'marker-without-registry'
    [IO.File]::Delete((Get-LifecycleFile $loose))
    NoFetch $loose 'lifecycle-unmanaged'
    Reject { Life 'Create' $loose '' } 'legacy existing path cannot be enrolled'
    $replaced=Fixture 'replaced-gitdir'
    $replacement=Fixture 'replacement-source'
    Move-Item -LiteralPath (Join-Path $replaced '.git') -Destination (Join-Path $script:Temp 'old-replaced-git')
    Move-Item -LiteralPath (Join-Path $replacement '.git') -Destination (Join-Path $replaced '.git')
    NoFetch $replaced 'lifecycle-identity-changed'
    $rootReplaced=Fixture 'replaced-root'
    Move-Item -LiteralPath $rootReplaced -Destination (Join-Path $script:Temp 'old-replaced-root')
    [void](Git $script:Temp @('clone','--no-hardlinks','--quiet',$script:Remote,$rootReplaced))
    [void](Git $rootReplaced @('remote','set-url','origin',$script:ExpectedOrigin))
    NoFetch $rootReplaced 'lifecycle-identity-changed'
    $pending=Fixture 'crash-before-replace'
    $r=Claim $pending; $r=Life 'Resume' $pending $r.Claim
    # Interrupted temp write is never read as authority; old active state wins.
    [IO.File]::WriteAllText(((Get-LifecycleFile $pending)+'.pending-synthetic'),'State=completed')
    NoFetch $pending 'lifecycle-not-completed'
    $retired=Fixture 'durable-retirement'
    Invoke-WorkspaceLock { $r=Get-LifecycleRecord $retired; $r.State='deleting'; Write-LifecycleRecord $retired $r }
    Reject { Life 'Resume' $retired (Claim $retired).Claim } 'crash after deleting record cannot resume'
    [IO.File]::Delete((Join-Path $retired 'file.txt'))
    NoFetch $retired 'lifecycle-not-completed'
    $gone=Fixture 'tombstone'
    $r=Claim $gone
    [void](Check $gone 'removed' $true)
    Assert ((Claim $gone).State -eq 'deleted') 'deleted tombstone persists outside deleted directory'
    Reject { Life 'Resume' $gone $r.Claim } 'deleted cannot resume'
    Reject { Life 'Create' $gone '' } 'deleted path cannot be reused'
    # No-follow registry writes must not change an external hardlink target.
    $linked=Fixture 'linked-registry'
    $linkedFile=Get-LifecycleFile $linked
    [IO.File]::Delete($linkedFile)
    $claimSentinel=Join-Path $script:Temp 'claim-sentinel'
    [IO.File]::WriteAllText($claimSentinel,$valid)
    [void](New-Item -ItemType HardLink -Path $linkedFile -Target $claimSentinel)
    Reject { [HealthCheck.WorkspaceCleanup.Tree]::WriteState($linkedFile,'bad',$false) } 'linked registry write refused'
    Assert ([IO.File]::ReadAllText($claimSentinel) -ceq $valid) 'external registry target unchanged'
    NoFetch $linked 'filesystem-or-check-unknown'
    # Actual second PowerShell process and one mutex exercise both race winners.
    $worker=Join-Path $script:Temp 'lifecycle-worker.ps1'
    $workerText=@'
param($Source,$Client,$Ops,$Mutex,$Target,$Token,$Remote,$Ready,$Release,$Mode)
$ErrorActionPreference='Stop'
. $Source
Initialize-JanitorNative
$script:ApprovedRoots=@($Client); $script:LogDirectory=$Ops; $script:WorkspaceMutexName=$Mutex
function Get-JanitorProcesses { [pscustomobject]@{ Known=$true; Commands=@(); HiddenProcessCommandLines=0 } }
$script:OriginalGit=${function:Invoke-JanitorGit}
function Invoke-JanitorGit([string]$Path,[string[]]$Arguments) {
    if ($Arguments[0] -eq 'fetch') { $Arguments=$Arguments.Clone(); $Arguments[4]=$Remote }
    & $script:OriginalGit $Path $Arguments
}
function Rendezvous {
    [IO.File]::WriteAllText($Ready,'ready')
    $until=[datetime]::UtcNow.AddSeconds(15)
    while(-not [IO.File]::Exists($Release)) { if([datetime]::UtcNow -gt $until){throw 'fixture-timeout'}; Start-Sleep -Milliseconds 20 }
}
if($Mode -eq 'resume') {
    Invoke-WorkspaceLock { Invoke-WorkspaceLifecycle 'Resume' $Target 'synthetic' $Token | Out-Null; Rendezvous }
} else {
    $script:OriginalWrite=${function:Write-LifecycleRecord}
    function Write-LifecycleRecord([string]$Path,$Record,[switch]$Create) {
        & $script:OriginalWrite $Path $Record -Create:$Create
        if($Record.State -eq 'deleting') { Rendezvous; [Environment]::Exit(0) }
    }
    Invoke-WorkspaceLock { Invoke-JanitorTask $Target 7 $true ([datetime]::UtcNow) | Out-Null }
}
'@
    [IO.File]::WriteAllText($worker,$workerText)
    foreach ($mode in @('resume','janitor')) {
        $target=Fixture ('race-'+$mode)
        $token=(Claim $target).Claim
        $ready=Join-Path $script:Temp ('ready-'+$mode); $release=Join-Path $script:Temp ('release-'+$mode)
        # Keep a handle open so a child exiting while holding it is observably abandoned.
        $observer=New-Object Threading.Mutex($false,$script:WorkspaceMutexName)
        $start=New-Object Diagnostics.ProcessStartInfo
        $start.FileName=(Join-Path $PSHOME 'powershell.exe'); $start.UseShellExecute=$false; $start.CreateNoWindow=$true
        $start.RedirectStandardOutput=$true; $start.RedirectStandardError=$true
        $source=Join-Path $PSScriptRoot '..\scripts\cleanup-workspaces.ps1'
        $start.Arguments=(@('-NoLogo','-NoProfile','-NonInteractive','-File',$worker,$source,$script:Client,$script:LogDirectory,$script:WorkspaceMutexName,$target,$token,$script:Remote,$ready,$release,$mode) | ForEach-Object { Quote-JanitorArgument $_ }) -join ' '
        $child=New-Object Diagnostics.Process; $child.StartInfo=$start
        try {
            [void]$child.Start(); $stdout=$child.StandardOutput.ReadToEndAsync(); $stderr=$child.StandardError.ReadToEndAsync()
            $until=[datetime]::UtcNow.AddSeconds(15)
            while(-not [IO.File]::Exists($ready)) {
                if($child.HasExited -or [datetime]::UtcNow -gt $until) { throw ('fixture child failed '+$mode+': '+$stderr.GetAwaiter().GetResult()) }
                Start-Sleep -Milliseconds 20
            }
            if($mode -eq 'resume') {
                Reject { Invoke-WorkspaceLock { Invoke-JanitorTask $target 7 $true ([datetime]::UtcNow) } } 'Resume owns mutex: janitor cannot enter' 'workspace-busy'
            } else {
                Reject { Invoke-WorkerLifecycle -Action Resume -Workspace $target -Owner 'synthetic' -ClaimId $token } 'janitor owns mutex: worker Resume cannot enter' 'workspace-busy'
            }
        } finally {
            [IO.File]::WriteAllText($release,'release')
            if(-not $child.WaitForExit(20000)) { throw 'fixture child did not finish' }
            $exit=$child.ExitCode; $child.Dispose()
        }
        Assert ($exit -eq 0) 'child race process exited successfully'
        if($mode -eq 'resume') { NoFetch $target 'lifecycle-not-completed' }
        else {
            # Child crashed after durable deleting, before any unlink. Acquisition
            # handles abandoned mutex, but must not clear the retirement record.
            Reject { Invoke-WorkerLifecycle -Action Resume -Workspace $target -Owner 'synthetic' -ClaimId $token } 'worker Resume preserves deleting after abandoned mutex' 'lifecycle-retired'
            Assert ((Claim $target).State -eq 'deleting') 'durable crash retirement retained'
            NoFetch $target 'lifecycle-not-completed'
        }
        $observer.Dispose()
    }
    foreach ($forbidden in @($outside,$seed,$script:LogDirectory,(Join-Path $outside 'nested'))) {
        [void](Check $forbidden 'root-rejected' $true)
    }
    Assert ([IO.File]::Exists((Join-Path $seed 'file.txt')) -and [IO.Directory]::Exists($outside)) 'zero deletions outside approved immediate children'

    # End-to-end consumer used by the worker task/checkout workflow. No new launcher
    # and no mocked lifecycle operations: the accepted script was dot-sourced above.
    $workerTask=Join-Path $script:Client 'worker-consumer'
    Assert ($taskOwner -ceq 'synthetic-worker') 'documented task owner survives dot-source parameter binding'
    $workerOwner=$taskOwner
    $workerClaim=Invoke-WorkerLifecycle -Action Create -Workspace $workerTask -Owner $workerOwner
    Assert ($workerClaim.State -ceq 'active' -and $workerClaim.GitId -ceq '-') 'worker Create owns a fresh unbound clone destination'
    Reject { Invoke-WorkerLifecycle -Action CheckActive -Workspace $workerTask -Owner $workerOwner -ClaimId $workerClaim.Claim } 'worker cannot write through unbound active check' 'lifecycle-unbound'
    [void](Git $script:Temp @('clone','--no-hardlinks','--quiet',$script:Remote,$workerTask))
    [void](Git $workerTask @('remote','set-url','origin',$script:ExpectedOrigin))
    $script:RemoteFor[$workerTask]=$script:Remote
    $workerClaim=Invoke-WorkerLifecycle -Action Bind -Workspace $workerTask -Owner $workerOwner -ClaimId $workerClaim.Claim
    $global:LASTEXITCODE=73 # Deliberately stale native status must not authorize/reject a worker call.
    $workerClaim=Invoke-WorkerLifecycle -Action CheckActive -Workspace $workerTask -Owner $workerOwner -ClaimId $workerClaim.Claim
    Assert ($workerClaim.State -ceq 'active' -and $global:LASTEXITCODE -eq 73) 'worker receives a typed active object independently of native exit status'
    [void](Git $workerTask @('switch','-c','synthetic-worker-delivery'))
    Commit $workerTask 'synthetic-worker-delivered'
    $workerClaim=Invoke-WorkerLifecycle -Action CheckActive -Workspace $workerTask -Owner $workerOwner -ClaimId $workerClaim.Claim
    [void](Git $workerTask @('push',$script:Remote,'HEAD:refs/heads/main'))
    $deliveredHead=Git $workerTask @('rev-parse','HEAD')
    $workerReceipt=Join-Path $script:Temp 'worker-delivery-checkpoint.json'
    [IO.File]::WriteAllText($workerReceipt,([ordered]@{head=$deliveredHead;claim=$workerClaim.Claim;generation=$workerClaim.Generation}|ConvertTo-Json))
    $deliveredUtc=[datetime]::UtcNow
    $workerClaim=Invoke-WorkerLifecycle -Action Pause -Workspace $workerTask -Owner $workerOwner -ClaimId $workerClaim.Claim
    $workerOldClaim=$workerClaim.Claim
    Reject { Invoke-WorkerLifecycle -Action CheckActive -Workspace $workerTask -Owner $workerOwner -ClaimId $workerOldClaim } 'paused diagnostic success is not worker authorization' 'lifecycle-not-active'
    $diagnostic=Invoke-WorkspaceLock { Invoke-WorkspaceLifecycle 'Check' $workerTask $workerOwner $workerOldClaim }
    Assert ($diagnostic.State -ceq 'paused') 'diagnostic Check remains distinct from worker guard'
    $workerClaim=Invoke-WorkerLifecycle -Action Resume -Workspace $workerTask -Owner $workerOwner -ClaimId $workerOldClaim
    Assert ($workerClaim.Claim -cne $workerOldClaim -and $workerClaim.Generation -ceq '2') 'worker Resume returns a new Claim and generation'
    [IO.File]::WriteAllText($workerReceipt,([ordered]@{head=$deliveredHead;claim=$workerClaim.Claim;generation=$workerClaim.Generation}|ConvertTo-Json))
    $resumedReceipt=[IO.File]::ReadAllText($workerReceipt)|ConvertFrom-Json
    Reject { Invoke-WorkerLifecycle -Action CheckActive -Workspace $workerTask -Owner $workerOwner -ClaimId $workerOldClaim } 'worker old checkpoint cannot authorize continuation' 'lifecycle-owner-or-claim-mismatch'
    $workerClaim=Invoke-WorkerLifecycle -Action CheckActive -Workspace $workerTask -Owner $workerOwner -ClaimId $resumedReceipt.claim
    NoFetch $workerTask 'lifecycle-not-completed'
    $workerClaim=Invoke-WorkerLifecycle -Action Complete -Workspace $workerTask -Owner $workerOwner -ClaimId $workerClaim.Claim
    Assert ($workerClaim.State -ceq 'completed' -and $workerClaim.Head -ceq $deliveredHead -and [long]$workerClaim.Completed -ge $deliveredUtc.Ticks) 'worker Complete follows actual synthetic delivery and records its exact HEAD'
    Reject { Invoke-WorkerLifecycle -Action CheckActive -Workspace $workerTask -Owner $workerOwner -ClaimId $workerClaim.Claim } 'completed claim cannot authorize worker edits' 'lifecycle-not-active'
    Reject { Invoke-WorkerLifecycle -Action Check -Workspace $workerTask -Owner $workerOwner -ClaimId $workerClaim.Claim } 'worker API deliberately excludes diagnostic Check'
    [void](Check $workerTask 'younger-than-retention')
    Assert ([IO.Directory]::Exists($workerTask)) 'consumer E2E performs no cleanup Apply'

    # Bounded sanitized report and production runner dry-run, with synthetic fixed roots.
    Old $clean
    $script:CimRows=@(
        [pscustomobject]@{ ProcessId=123; CommandLine=$null },
        [pscustomobject]@{ ProcessId=124; CommandLine='SYNTHETIC_UNRELATED_COMMAND --private-argument' }
    )
    $report=Invoke-WorkspaceJanitor @($script:Client) 7
    $json=$report | ConvertTo-Json -Depth 5
    Assert ($json -notmatch 'SECRET_HEALTH_VALUE|example.invalid|synthetic@example|same-patch') 'no content/URL/commit messages in report'
    Assert ($json -notmatch 'SYNTHETIC_UNRELATED_COMMAND|private-argument|"Commands"|ProcessId') 'runner report never exposes unrelated process commands or identifiers'
    $cleanReport=@($report.Records | Where-Object { $_.Task -eq 'clean-merged' })[0]
    Assert ($cleanReport.HiddenProcessCommandLines -eq 1 -and $cleanReport.Result -eq 'ELIGIBLE') 'runner report exposes count only and keeps eligibility'
    $log=Join-Path $script:LogDirectory 'workspace-cleanup-latest.json'
    Assert ([IO.File]::Exists($log) -and (Get-Item $log).Length -lt 262144) 'bounded fixed latest Ops summary'
    Assert ([IO.Directory]::Exists($clean)) 'runner default dry-run preserved eligible clone'
    # Summary writer must not overwrite a linked destination, even with a valid filename.
    Remove-Item -LiteralPath $log
    $sentinel=Join-Path $script:Temp 'log-sentinel.txt'
    [IO.File]::WriteAllText($sentinel,'synthetic sentinel')
    [void](New-Item -ItemType HardLink -Path $log -Target $sentinel)
    $failed=$false; try { Save-JanitorReport $report } catch { $failed=$true }
    Assert $failed 'linked Ops log rejected'
    Assert ([IO.File]::ReadAllText($sentinel) -eq 'synthetic sentinel') 'linked log target untouched'
    $failed=$false; try { [void](Invoke-WorkspaceJanitor @($script:Client) 7 -Delete) } catch { $failed=$true }
    Assert ($failed -and [IO.Directory]::Exists($clean)) 'unsafe initial log prevents Apply'
    Remove-Item -LiteralPath $log
    $stopRoot=Join-Path $script:Temp 'stop-client'
    [void][IO.Directory]::CreateDirectory((Join-Path $stopRoot 'a-failure'))
    [void][IO.Directory]::CreateDirectory((Join-Path $stopRoot 'b-untouched'))
    $script:ApprovedRoots=@($stopRoot)
    $realTask=${function:Invoke-JanitorTask}; $script:Invocations=@()
    function Invoke-JanitorTask([string]$Path, [int]$Days, [bool]$Delete, [datetime]$Now) {
        $script:Invocations += $Path
        $record=New-JanitorRecord $Path
        $record.Result='ERROR'; $record.Reason='delete-failed-stop'
        return $record
    }
    try {
        $stopped=Invoke-WorkspaceJanitor @($stopRoot) 7 -Delete
        Assert ($stopped.Status -eq 'stopped' -and $script:Invocations.Count -eq 1) 'deletion failure stops remaining tasks'
        Assert ([IO.Directory]::Exists((Join-Path $stopRoot 'b-untouched'))) 'remaining workspace untouched'
    } finally { ${function:Invoke-JanitorTask}=$realTask; $script:ApprovedRoots=@($script:Client) }
    $report.Records | Where-Object { $_.Task -in @('clean-merged','unique','young','marker-owner-db') } | ConvertTo-Json -Depth 3
    Write-Output "PASS: $script:Assertions synthetic janitor assertions (Windows PowerShell $($PSVersionTable.PSVersion))"
} finally {
    Remove-Item Env:\GIT_AUTHOR_DATE -ErrorAction SilentlyContinue
    Remove-Item Env:\GIT_COMMITTER_DATE -ErrorAction SilentlyContinue
    if ($null -ne $junction -and [IO.Directory]::Exists($junction)) { (Get-Item -LiteralPath $junction -Force).Delete() }
    # Exact harness-owned temp boundary; no cross-shell or computed project-root deletion.
    $resolved=[IO.Path]::GetFullPath($script:Temp)
    $parent=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    if ([IO.Path]::GetDirectoryName($resolved) -ne $parent -or [IO.Path]::GetFileName($resolved) -notmatch '^healthcheck-janitor-[a-f0-9]{32}$') { throw 'fixture cleanup boundary failed' }
    if (@(Get-ChildItem -LiteralPath $resolved -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw 'fixture cleanup reparse remains' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
