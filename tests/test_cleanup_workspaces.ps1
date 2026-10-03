# Self-contained Windows PowerShell 5.1 synthetic regression; no Owner roots/data.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
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
}
function Commit([string]$Path, [string]$Value) {
    [IO.File]::WriteAllText((Join-Path $Path 'file.txt'), $Value)
    [void](Git $Path @('add','file.txt'))
    [void](Git $Path @('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-m','synthetic'))
}
function Fixture([string]$Name) {
    $repo = Join-Path $script:Client $Name
    [void](Git $script:Temp @('clone','--no-hardlinks','--quiet',$script:Remote,$repo))
    [void](Git $repo @('remote','set-url','origin',$script:ExpectedOrigin))
    $script:RemoteFor[$repo]=$script:Remote
    Old $repo
    return $repo
}
function Check([string]$Path, [string]$Reason, [bool]$Delete=$false) {
    $out = @(Invoke-JanitorTask $Path 7 $Delete ([datetime]::UtcNow))
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
    $record=Check $worktree 'removed' $true
    Assert ($record.Git -eq 'worktree') 'linked worktree classified'
    Assert (-not [IO.Directory]::Exists($worktree)) 'linked worktree removed'
    $removeCalls=@($script:Calls | Where-Object { $_.Args.Count -gt 1 -and $_.Args[0] -eq 'worktree' -and $_.Args[1] -eq 'remove' })
    Assert ($removeCalls.Count -eq 1 -and $removeCalls[0].Args -notcontains '--force' -and $removeCalls[0].Args -notcontains '-f') 'non-force Git primitive only'
    Assert ((Git $owner @('worktree','list','--porcelain')) -notmatch 'linked-worktree') 'only removed registration retired'
    $locked=Join-Path $script:Client 'locked-worktree'
    [void](Git $owner @('worktree','add','--detach',$locked,'HEAD'))
    [void](Git $owner @('worktree','lock',$locked))
    $script:RemoteFor[$locked]=$script:Remote
    Old $owner; Old $locked
    $record=Check $locked 'delete-failed-stop' $true
    Assert ($record.Result -eq 'ERROR' -and [IO.Directory]::Exists($locked)) 'failed Git removal preserves locked worktree'
    [void](Git $owner @('worktree','unlock',$locked))
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
