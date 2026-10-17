<#
.SYNOPSIS
Fail-closed cleanup of disposable Health-Check task workspaces (Windows PowerShell 5.1+).
.DESCRIPTION
Dry-run is the default. -Retire moves eligible clones to recovery; -Apply is refused. Roots are a fixed
allowlist, not an arbitrary filesystem cleanup interface. Fetch updates only local
origin tracking refs. No remote branch is deleted. Every unknown is PRESERVE.
A bounded, overwritten JSON summary is saved to the fixed Owner Ops directory.
Use the matching lifecycle operations before any managed checkout writes/resume.
Only explicitly completed enrolled standalone clones may reach fetch/retirement.
Fetch is mandatory for completed candidates even in dry-run and updates local Git metadata. Conservatively,
that write can postpone eligibility at a later invocation. Unknown process command
lines, ignored non-cache files, non-cache hardlinks, SSH/alternate origin URL spellings and
metadata outside these roots are preserved. Max 200 tasks / 25,000 entries per task.
#>
[CmdletBinding()]
param(
    [string[]]$Root = @('D:\HealthCheck\workspaces\codex', 'D:\HealthCheck\workspaces\opencode',
        'D:\HealthCheck\workspaces\grok', 'D:\HealthCheck\workspaces\hermes'),
    [int]$RetentionDays = 7,
    [switch]$Apply,
    [switch]$Retire,
    [ValidateSet('Scan','Create','Bind','Check','CheckActive','Pause','Resume','Complete','Recover','Restore')][string]$Operation='Scan',
    [string]$Workspace,
    [string]$Owner,
    [string]$ClaimId
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ApprovedRoots = @('D:\HealthCheck\workspaces\codex', 'D:\HealthCheck\workspaces\opencode',
    'D:\HealthCheck\workspaces\grok', 'D:\HealthCheck\workspaces\hermes')
$script:ExpectedOrigin = 'https://github.com/LTstripes/Health-Check.git'
$script:LogDirectory = 'D:\HealthCheck\ops'
$script:RecoveryDirectory = 'D:\HealthCheck\recovery\workspaces'
$script:EntryLimit = 25000
$script:TaskLimit = 200
$script:WorkspaceMutexName = 'Global\HealthCheck.WorkspaceCleanup'
$script:WorkspaceMutexHeld = $false

function Initialize-JanitorNative {
    if (-not ('HealthCheck.WorkspaceCleanup.Tree' -as [type])) {
        Add-Type -Path (Join-Path $PSScriptRoot 'cleanup-workspaces.fs.cs')
    }
}
function Get-JanitorPath([string]$Path) {
    if ($Path -notmatch '^[A-Za-z]:\\' -or $Path.Contains('/') -or $Path.Substring(2).Contains(':')) { throw 'path-rejected' }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $full.Equals($Path.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) { throw 'path-rejected' }
    return $full
}
function Assert-JanitorRoot([string]$Path) {
    $full = Get-JanitorPath $Path
    if ($script:ApprovedRoots -notcontains $full) { throw 'root-rejected' }
    return $full
}
function Assert-JanitorChild([string]$Path) {
    $full = Get-JanitorPath $Path
    $parent = [IO.Path]::GetDirectoryName($full)
    [void](Assert-JanitorRoot $parent)
    # Only sanitized ASCII task names can be logged or used as Git command arguments.
    if ([IO.Path]::GetFileName($full) -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$') { throw 'task-name-rejected' }
    return $full
}
function Quote-JanitorArgument([string]$Value) {
    # Windows CommandLineToArgvW quoting (never invoke a shell).
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}
function Invoke-JanitorGit([string]$Path, [string[]]$Arguments) {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = (Get-Command git.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $args = @('--no-optional-locks', '--no-replace-objects', '-c', "safe.directory=$Path", '-c', 'core.hooksPath=NUL',
        '-c', 'core.fsmonitor=false', '-C', $Path) + $Arguments
    $start.Arguments = ($args | ForEach-Object { Quote-JanitorArgument $_ }) -join ' '
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($key in @($start.EnvironmentVariables.Keys)) {
        if ($key -like 'GIT_*') { $start.EnvironmentVariables.Remove($key) }
    }
    $start.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
    $start.EnvironmentVariables['GCM_INTERACTIVE'] = 'never'
    $start.EnvironmentVariables['GIT_OPTIONAL_LOCKS'] = '0'
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(120000)) { $process.Kill(); throw 'git-timeout' }
        $out = $stdout.GetAwaiter().GetResult()
        $err = $stderr.GetAwaiter().GetResult()
        if ($out.Length -gt 262144 -or $err.Length -gt 262144) { throw 'git-output-limit' }
        # Raw diagnostics may contain URLs, credentials or filenames. Never print them.
        return [pscustomobject]@{ Code=$process.ExitCode; Text=$out.TrimEnd("`r", "`n") }
    } finally { $process.Dispose() }
}
function Get-JanitorGitText([string]$Path, [string[]]$Arguments) {
    $result = Invoke-JanitorGit $Path $Arguments
    if ($result.Code -ne 0) { throw 'git-check-failed' }
    return $result.Text
}
function Get-JanitorProcesses {
    try { $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop) }
    catch { return [pscustomobject]@{ Known=$false; Commands=@(); HiddenProcessCommandLines=$null } }
    $commands = New-Object 'Collections.Generic.List[string]'
    $hidden = 0
    foreach ($process in $processes) {
        # Unavailable command lines are diagnostic only after successful enumeration.
        # Keep visible commands internal; reports expose only a count capped at 65535.
        $command = $null
        try {
            $property = $process.PSObject.Properties['CommandLine']
            if ($null -ne $property) { $command = [string]$property.Value }
        } catch { $command = $null }
        if ([string]::IsNullOrWhiteSpace($command)) { $hidden = [math]::Min(65535, $hidden + 1) }
        else { $commands.Add($command) }
    }
    return [pscustomobject]@{ Known=$true; Commands=@($commands.ToArray()); HiddenProcessCommandLines=$hidden }
}
function Test-JanitorProcess([string]$Path, $Processes) {
    if (-not $Processes.Known) { throw 'process-state-unknown' }
    foreach ($command in $Processes.Commands) {
        if ($command.IndexOf($Path, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            $command.IndexOf($Path.Replace('\', '/'), [StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'active-process' }
    }
}
function Get-JanitorCacheProof($Tree, [string]$Path) {
    $proof=@{}
    $candidates=@($Tree.Entries | Where-Object { $null -ne $_.CacheRoot })
    if (-not $candidates.Count) { return $proof }
    $tracked=New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($file in (Get-JanitorGitText $Path @('ls-files', '-z')).Split([char]0)) {
        if ($file) { [void]$tracked.Add((Join-Path $Path ($file.Replace('/', '\')))) }
    }
    foreach ($cacheRoot in @($candidates | ForEach-Object { $_.CacheRoot } | Select-Object -Unique)) {
        $relative=$cacheRoot.Substring($Path.Length + 1).Replace('\', '/')
        if ([IO.Directory]::Exists($cacheRoot)) { $relative += '/' }
        $check=Invoke-JanitorGit $Path @('check-ignore', '--quiet', '--no-index', '--', $relative)
        if ($check.Code -ne 0) { throw 'generated-cache-unproven' }
    }
    foreach ($entry in $candidates) {
        # Every cache file is absent from the index. Git ignores its directory root
        # (or the exact loose bytecode file); an ignored parent excludes descendants.
        # Scan has pinned all ancestors and rejected reparse/alias paths. The existing
        # full clean-status guard remains mandatory; no dependency contents are read.
        if ($tracked.Contains($entry.Path)) {
            throw 'generated-cache-unproven'
        }
        $proof[$entry.Path]=$entry.Stamp
        $Tree.ApproveGeneratedCache($entry.Path, $entry.Stamp)
    }
    return $proof
}
function Set-JanitorCacheProof($Tree, $Proof) {
    foreach ($entry in $Tree.Entries) {
        if ($Proof.ContainsKey($entry.Path)) { $Tree.ApproveGeneratedCache($entry.Path, $Proof[$entry.Path]) }
        elseif ($null -ne $entry.CacheRoot) { throw 'generated-cache-unproven' }
    }
}
function Test-JanitorMarkers($Entries, [string]$Path) {
    foreach ($entry in $Entries) {
        $relative = $entry.Path.Substring($Path.Length).TrimStart('\')
        $name = [IO.Path]::GetFileName($entry.Path)
        $cache = $null -ne $entry.PSObject.Properties['GeneratedCache'] -and $entry.GeneratedCache
        if ($entry.Directory) {
            # Strong private boundaries are never exempted, even within a cache.
            if ($name -match '^(private|profiles?|backups?|recovery|credentials?|secrets?|tokens?|\.aws|\.ssh|\.gnupg)$') { throw 'private-runtime-marker' }
            # Known caches may contain normal package data, images, logs and runtime assets.
            if (-not $cache -and $relative -notin @('src\healthcheck\ingestion\photo', '.git\logs') -and
                $relative -notmatch '^\.git\\worktrees\\[A-Za-z0-9._-]+\\logs$' -and $name -match '^(data|runtime|artifacts|payloads?|photos?|screenshots?|logs|reports)$') { throw 'private-runtime-marker' }
        } else {
            if ($name -match '(?i)\.(db|sqlite|sqlite3)(-|$)|\.(age|bak|backup|key|pfx|secret|token)$' -or
                $name -match '^(config\.toml|collection-policy\.json|\.env|\.env\..+)$' -and $name -ne '.env.example' -or
                $name -match '(?i)(credential|refresh.?token|access.?token|bind.?key|session|oauth).*(\.(json|bin|dat|enc|txt|toml))$') { throw 'private-runtime-marker' }
            if (-not $cache -and $name -match '(?i)\.(zip|7z|rar|tar|tgz|gz|bz2|xz|zst|pem|pdf|jpe?g|png|heic|webp|gif|bmp|tiff?|dcm)$') { throw 'private-runtime-marker' }
        }
    }
}
function Get-JanitorAge($Tree, [string]$Path, [datetime]$Now) {
    $stamp = Get-JanitorGitText $Path @('show', '-s', '--format=%ct', 'HEAD')
    $epoch = 0L
    if (-not [long]::TryParse($stamp, [ref]$epoch)) { throw 'age-unknown' }
    $latest = ([datetime]'1970-01-01T00:00:00Z').ToUniversalTime().AddSeconds($epoch)
    foreach ($entry in $Tree.Entries) { if ($entry.Written -gt $latest) { $latest = $entry.Written } }
    if ($latest -gt $Now) { throw 'age-unknown' }
    return ($Now - $latest).TotalDays
}
function Get-JanitorGitState([string]$Path, $Guard) {
    # Validate the .git topology before allowing Git to open referenced metadata.
    $dotgit = Join-Path $Path '.git'
    if ([IO.File]::Exists($dotgit)) {
        $pointer = [HealthCheck.WorkspaceCleanup.Tree]::ReadGitPointer($dotgit)
        if ($pointer -notmatch '^gitdir: ([A-Za-z]:[\\/].+)$') { throw 'external-git-metadata' }
        $metadata = Get-JanitorPath ($Matches[1].Replace('/', '\'))
        $metadataParent = [IO.Path]::GetDirectoryName($metadata)
        if ([IO.Path]::GetFileName($metadataParent) -ne 'worktrees') { throw 'external-git-metadata' }
        $metadataCommon = [IO.Path]::GetDirectoryName($metadataParent)
        $metadataOwner = Assert-JanitorChild ([IO.Path]::GetDirectoryName($metadataCommon))
        if ($metadataCommon -ne (Join-Path $metadataOwner '.git')) { throw 'external-git-metadata' }
        $Guard.PinAncestors($metadataCommon)
        $probe = New-Object HealthCheck.WorkspaceCleanup.Tree($false)
        try { $probe.PinAncestors($metadata) } finally { $probe.Dispose() }
    } elseif (-not [IO.Directory]::Exists($dotgit)) { throw 'not-task-checkout' }
    $top = (Get-JanitorGitText $Path @('rev-parse', '--show-toplevel')).Replace('/', '\')
    if (-not $top.Equals($Path, [StringComparison]::OrdinalIgnoreCase)) { throw 'not-task-checkout' }
    $common = (Get-JanitorGitText $Path @('rev-parse', '--path-format=absolute', '--git-common-dir')).Replace('/', '\')
    $gitdir = (Get-JanitorGitText $Path @('rev-parse', '--absolute-git-dir')).Replace('/', '\')
    # Metadata may belong only to a real task checkout within the approved roots.
    $owner = Assert-JanitorChild ([IO.Path]::GetDirectoryName($common))
    if (-not $common.Equals((Join-Path $owner '.git'), [StringComparison]::OrdinalIgnoreCase)) { throw 'external-git-metadata' }
    if ($owner -ne $Path) { $Guard.PinAncestors($common) }
    $origin = Invoke-JanitorGit $Path @('config', '--get-all', 'remote.origin.url')
    if ($origin.Code -ne 0 -or $origin.Text -cne $script:ExpectedOrigin) { throw 'wrong-origin' }
    $rewrite = Invoke-JanitorGit $Path @('config', '--get-regexp', '^url\..*\.(insteadof|pushinsteadof)$')
    if ($rewrite.Code -ne 1) { throw 'remote-rewrite-or-unknown' }
    $registered = Get-JanitorGitText $Path @('worktree', 'list', '--porcelain')
    $worktrees = @($registered -split "`n" | Where-Object { $_ -like 'worktree *' } | ForEach-Object { $_.Substring(9).TrimEnd("`r").Replace('/', '\') })
    if ($worktrees -notcontains $Path) { throw 'registration-unknown' }
    $kind = 'clone'
    if (-not $gitdir.Equals($common, [StringComparison]::OrdinalIgnoreCase)) {
        $kind = 'worktree'
        if ($worktrees -notcontains $owner -or $gitdir -notlike "$common\worktrees\*" -or
            [IO.Path]::GetDirectoryName($gitdir) -ne (Join-Path $common 'worktrees')) { throw 'registration-unknown' }
        if ($gitdir -ne $metadata) { throw 'registration-unknown' }
    } elseif ($owner -ne $Path -or $worktrees.Count -ne 1) { throw 'dependent-worktrees' }
    return [pscustomobject]@{ Kind=$kind; Common=$common; Owner=$owner }
}
function Test-JanitorClean([string]$Path) {
    if ((Get-JanitorGitText $Path @('status', '--porcelain=v1', '--untracked-files=all', '--ignore-submodules=none')).Length) { throw 'dirty-or-untracked' }
    if ((Get-JanitorGitText $Path @('ls-files', '--stage')) -match '(?m)^160000 ') { throw 'submodule-unknown' }
    # Unknown ignored material is preserved, including outside recognizable caches.
    # Exclude only recognized generated paths from this unknown-material query.
    # Their ignored roots/index absence are separately proved, without a multi-MB
    # list of every .venv dependency asset overflowing the bounded Git output.
    $ignored = Get-JanitorGitText $Path @('ls-files', '--others', '--ignored', '--exclude-standard', '-z', '--', '.',
        ':(icase,glob,exclude).venv/**', ':(icase,glob,exclude).pytest_cache/**', ':(icase,glob,exclude).ruff_cache/**',
        ':(icase,glob,exclude)**/__pycache__/**', ':(icase,glob,exclude)**/*.py[co]')
    foreach ($file in @($ignored.Split([char]0) | Where-Object { $_ })) {
        if ($file -notmatch '^(\.venv/|\.pytest_cache/|\.ruff_cache/|(.*/)?__pycache__/|.*\.py[co]$)') { throw 'unknown-ignored-material' }
    }
}
function Test-JanitorRefs([string]$Path) {
    [void](Get-JanitorGitText $Path @('rev-parse', '--verify', 'refs/remotes/origin/main^{commit}'))
    $reachable = Invoke-JanitorGit $Path @('merge-base', '--is-ancestor', 'HEAD', 'refs/remotes/origin/main')
    if ($reachable.Code -eq 1) {
        $cherry = Get-JanitorGitText $Path @('cherry', 'refs/remotes/origin/main', 'HEAD')
        if ($cherry -match '(?m)^\+') { throw 'unique-head-commit' }
    } elseif ($reachable.Code -ne 0) { throw 'ancestry-unknown' }
    $refs = Get-JanitorGitText $Path @('for-each-ref', '--format=%(refname)')
    foreach ($ref in @($refs -split "`n" | Where-Object { $_ -and $_ -notlike 'refs/remotes/origin/*' })) {
        # Replacements/notes/noncommit objects are not ordinary disposable history.
        if ($ref -notmatch '^refs/(heads|tags|stash)(/|$)') { throw 'unknown-local-ref' }
        [void](Get-JanitorGitText $Path @('rev-parse', '--verify', "$ref^{commit}"))
        $count = Get-JanitorGitText $Path @('rev-list', '--count', $ref, '--not', '--remotes=origin')
        if ($count -ne '0') { throw 'unique-local-ref' }
    }
}
# Versioned cooperative lifecycle. No adoption of existing/legacy checkouts.
# Callers must use the same mutex before writing, resuming or retiring a checkout.
function Assert-WorkspaceLock {
    if (-not $script:WorkspaceMutexHeld) { throw 'lifecycle-lock-required' }
}
function Get-LifecycleFile([string]$Path) {
    return Join-Path $script:LogDirectory ('workspace-claim-' + [HealthCheck.WorkspaceCleanup.Tree]::StateKey($Path) + '.state')
}
function ConvertTo-LifecycleText($Record, [switch]$Marker) {
    $keys = @('Format','Path','RootId','GitId','Enrollment')
    if (-not $Marker) { $keys += @('Owner','Claim','Generation','State','Head','Completed'); if ($Record.Format -eq '2') { $keys += 'Transaction' } }
    return (($keys | ForEach-Object { $_ + '=' + [string]$Record[$_] }) -join "`n") + "`n"
}
function Read-LifecycleRecord([string]$File, [switch]$Marker) {
    # Exact ordered ASCII schema rejects duplicates, unknown fields, versions,
    # newline injection and malformed encodings. No permissive JSON coercions.
    $text = [HealthCheck.WorkspaceCleanup.Tree]::ReadState($File)
    $keys = @('Format','Path','RootId','GitId','Enrollment')
    if (-not $Marker) { $keys += @('Owner','Claim','Generation','State','Head','Completed') }
    if (-not $Marker -and $text.StartsWith("Format=2`n")) { $keys += 'Transaction' }
    $lines = $text.Split([char]10)
    if ($lines.Count -ne $keys.Count + 1 -or $lines[-1] -cne '') { throw 'lifecycle-invalid' }
    $record = [ordered]@{}
    for ($i=0; $i -lt $keys.Count; $i++) {
        $prefix=$keys[$i] + '='
        if (-not $lines[$i].StartsWith($prefix, [StringComparison]::Ordinal)) { throw 'lifecycle-invalid' }
        $record[$keys[$i]]=$lines[$i].Substring($prefix.Length)
    }
    if (($record.Format -cne '1' -and ($Marker -or $record.Format -cne '2')) -or $record.Path -cnotmatch '^[A-Za-z0-9+/]+={0,2}$' -or
        $record.RootId -cnotmatch '^\d+:\d+:\d+:\d+$' -or
        $record.GitId -cnotmatch '^(-|\d+:\d+:\d+:\d+)$' -or
        $record.Enrollment -cnotmatch '^[a-f0-9]{32}$') { throw 'lifecycle-invalid' }
    try {
        $decoded=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($record.Path))
        if ([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($decoded)) -cne $record.Path) { throw 'invalid' }
        [void](Get-JanitorPath $decoded)
    } catch { throw 'lifecycle-invalid' }
    if (-not $Marker) {
        if ($record.Owner -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$' -or
            $record.Claim -cnotmatch '^[a-f0-9]{32}$' -or $record.Generation -cnotmatch '^[1-9][0-9]{0,8}$' -or
            $record.State -cnotmatch '^(active|paused|completed|deleting|deleted|retiring|retired|restoring|needs_review)$' -or
            $record.Head -cnotmatch '^(-|[a-f0-9]{40}|[a-f0-9]{64})$' -or
            $record.Completed -cnotmatch '^(-|[0-9]{18})$') { throw 'lifecycle-invalid' }
        if (($record.Format -eq '2' -and ($record.State -notin @('retiring','retired','restoring','needs_review') -or $record.Transaction -cnotmatch '^[a-f0-9]{32}$')) -or
            ($record.Format -eq '1' -and $record.State -in @('retiring','retired','restoring','needs_review'))) { throw 'lifecycle-invalid' }
        if ($record.State -in @('completed','deleting','deleted','retiring','retired','restoring','needs_review')) {
            if ($record.GitId -eq '-' -or $record.Head -eq '-' -or $record.Completed -eq '-') { throw 'lifecycle-invalid' }
            try { [void](New-Object datetime ([long]$record.Completed, [DateTimeKind]::Utc)) } catch { throw 'lifecycle-invalid' }
        } elseif ($record.Head -ne '-' -or $record.Completed -ne '-') { throw 'lifecycle-invalid' }
    }
    return $record
}
function Write-LifecycleRecord([string]$Path, $Record, [switch]$Create) {
    Assert-WorkspaceLock
    [HealthCheck.WorkspaceCleanup.Tree]::WriteState((Get-LifecycleFile $Path), (ConvertTo-LifecycleText $Record), [bool]$Create)
}
function Get-LifecycleRecord([string]$Path) {
    Assert-WorkspaceLock
    $file=Get-LifecycleFile $Path
    if (-not [IO.File]::Exists($file)) { throw 'lifecycle-unmanaged' }
    $record=Read-LifecycleRecord $file
    $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Path.ToUpperInvariant()))
    if ($record.Path -cne $encoded) { throw 'lifecycle-identity-changed' }
    return $record
}
function Assert-LifecycleIdentity([string]$Path, $Record, [switch]$Bound) {
    if ($Record.RootId -cne [HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($Path)) { throw 'lifecycle-identity-changed' }
    $git=Join-Path $Path '.git'
    # v1 deliberately supports standalone clones only; no shared Common mutation.
    if ([IO.File]::Exists($git)) { throw 'shared-worktree-preserved' }
    if ($Record.GitId -ne '-') {
        if ($Record.GitId -cne [HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($git)) { throw 'lifecycle-identity-changed' }
        $marker=Read-LifecycleRecord (Join-Path $git 'workspace-enrollment.state') -Marker
        foreach ($key in @('Format','Path','RootId','GitId','Enrollment')) {
            if ($marker[$key] -cne $Record[$key]) { throw 'lifecycle-identity-changed' }
        }
    } elseif ($Bound) { throw 'lifecycle-unbound' }
    $legacy=Join-Path $git 'codex-owner.json'
    if ([IO.File]::Exists($legacy) -or [IO.Directory]::Exists($legacy)) { throw 'lifecycle-legacy-metadata' }
}
function Assert-LifecycleComplete([string]$Path, $Record, [datetime]$Now) {
    Assert-LifecycleIdentity $Path $Record -Bound
    if ($Record.State -cne 'completed') { throw 'lifecycle-not-completed' }
    if ((Get-JanitorGitText $Path @('rev-parse','HEAD')) -cne $Record.Head) { throw 'lifecycle-head-changed' }
    $completed=New-Object datetime ([long]$Record.Completed, [DateTimeKind]::Utc)
    if ($completed -gt $Now) { throw 'age-unknown' }
    return ($Now - $completed).TotalDays
}
function Invoke-WorkspaceLifecycle([string]$Action, [string]$Path, [string]$Owner, [string]$Token) {
    Assert-WorkspaceLock
    $path=Assert-JanitorChild $Path
    if ($Owner -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$') { throw 'lifecycle-owner-rejected' }
    $guard=New-Object HealthCheck.WorkspaceCleanup.Tree($false)
    $tree=$null
    try {
        $guard.PinAncestors([IO.Path]::GetDirectoryName($path))
        $guard.PinAncestors($script:LogDirectory)
        if ($Action -eq 'Create') {
            if ([IO.File]::Exists((Get-LifecycleFile $path))) { throw 'lifecycle-exists' }
            [HealthCheck.WorkspaceCleanup.Tree]::CreateFresh($path)
            $guard.PinAncestors($path)
            $record=[ordered]@{ Format='1'; Path=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($path.ToUpperInvariant()));
                RootId=[HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($path); GitId='-';
                Enrollment=[guid]::NewGuid().ToString('N'); Owner=$Owner; Claim=[guid]::NewGuid().ToString('N');
                Generation='1'; State='active'; Head='-'; Completed='-' }
            Write-LifecycleRecord $path $record -Create
            return [pscustomobject]$record
        }
        $record=Get-LifecycleRecord $path
        if ($record.Owner -cne $Owner -or $record.Claim -cne $Token) { throw 'lifecycle-owner-or-claim-mismatch' }
        if ($record.State -in @('deleting','deleted','retiring','retired','restoring','needs_review')) { throw 'lifecycle-retired' }
        Assert-NoPendingRetirement $path
        $guard.PinAncestors($path)
        Assert-LifecycleIdentity $path $record
        switch ($Action) {
            'Check' { }
            'CheckActive' {
                Assert-LifecycleIdentity $path $record -Bound
                if ($record.State -cne 'active') { throw 'lifecycle-not-active' }
            }
            'Bind' {
                if ($record.State -ne 'active' -or $record.GitId -ne '-') { throw 'lifecycle-transition-rejected' }
                $state=Get-JanitorGitState $path $guard
                if ($state.Kind -ne 'clone') { throw 'shared-worktree-preserved' }
                $guard.PinAncestors($state.Common)
                $record.GitId=[HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($state.Common)
                # Marker first: crash before registry commit leaves unbound => PRESERVE.
                [HealthCheck.WorkspaceCleanup.Tree]::WriteState((Join-Path $state.Common 'workspace-enrollment.state'), (ConvertTo-LifecycleText $record -Marker), $true)
                Write-LifecycleRecord $path $record
            }
            'Pause' {
                if ($record.State -ne 'active') { throw 'lifecycle-transition-rejected' }
                $record.State='paused'; Write-LifecycleRecord $path $record
            }
            'Resume' {
                if ($record.State -notin @('paused','completed')) { throw 'lifecycle-transition-rejected' }
                if ([int]$record.Generation -ge 999999999) { throw 'lifecycle-transition-rejected' }
                $record.Generation=([int]$record.Generation + 1).ToString([Globalization.CultureInfo]::InvariantCulture)
                $record.Claim=[guid]::NewGuid().ToString('N'); $record.State='active'; $record.Head='-'; $record.Completed='-'
                Write-LifecycleRecord $path $record
            }
            'Complete' {
                if ($record.State -ne 'active') { throw 'lifecycle-transition-rejected' }
                Assert-LifecycleIdentity $path $record -Bound
                $tree=New-Object HealthCheck.WorkspaceCleanup.Tree($false); $tree.Scan($path,$script:EntryLimit)
                Test-JanitorMarkers @($tree.Entries | Where-Object { $null -eq $_.CacheRoot }) $path
                [void](Get-JanitorGitState $path $guard)
                [void](Get-JanitorCacheProof $tree $path); Test-JanitorMarkers $tree.Entries $path
                Test-JanitorClean $path
                $record.Head=Get-JanitorGitText $path @('rev-parse','HEAD')
                $record.Completed=[datetime]::UtcNow.Ticks.ToString([Globalization.CultureInfo]::InvariantCulture)
                $record.State='completed'; Write-LifecycleRecord $path $record
            }
            default { throw 'lifecycle-transition-rejected' }
        }
        return [pscustomobject]$record
    } finally { if ($null -ne $tree) { $tree.Dispose() }; $guard.Dispose() }
}
function Invoke-WorkspaceLock([scriptblock]$Body) {
    $mutex=New-Object Threading.Mutex($false, $script:WorkspaceMutexName)
    $held=$false
    try {
        try { $held=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held=$true }
        if (-not $held) { throw 'workspace-busy' }
        $script:WorkspaceMutexHeld=$true
        & $Body
    } finally { $script:WorkspaceMutexHeld=$false; if ($held) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
}

function Invoke-WorkerLifecycle {
    <# Worker-facing consumer API. Dot-source the accepted installed pair first.
       Explicit checkout workflow, not a platform task event hook.
       Returns one claim object, or throws; does not launch an agent/runtime. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [ValidateSet('Create','Bind','CheckActive','Pause','Resume','Complete')][string]$Action,
        [Parameter(Mandatory=$true)][string]$Workspace,
        [Parameter(Mandatory=$true)][string]$Owner,
        [string]$ClaimId=''
    )
    if ($Action -ne 'Create' -and $ClaimId -cnotmatch '^[a-f0-9]{32}$') { throw 'lifecycle-owner-or-claim-mismatch' }
    Initialize-JanitorNative
    Invoke-WorkspaceLock { Invoke-WorkspaceLifecycle $Action $Workspace $Owner $ClaimId }
}
function New-JanitorRecord([string]$Path) {
    return [pscustomobject]@{ Task=[IO.Path]::GetFileName($Path); Path=$Path; AgeDays=$null; Git='unknown'; HiddenProcessCommandLines=$null; Result='PRESERVE'; Reason='check-unknown' }
}
function Get-JanitorSnapshot($Tree, [string]$Path) {
    # Fetch writes its own Git metadata. It must neither make an old workspace young
    # nor mask new activity in work files. Pin/compare all non-Git entries instead.
    $snapshot = @{}
    foreach ($entry in $Tree.Entries) {
        if ($entry.Path -ne $Path -and $entry.Path.Substring($Path.Length) -match '^\\\.git(\\|$)') { continue }
        $snapshot[$entry.Path] = $entry.Stamp
    }
    return $snapshot
}
function Assert-JanitorSnapshot($Before, $After) {
    if ($Before.Count -ne $After.Count) { throw 'workspace-changed' }
    foreach ($key in $Before.Keys) { if (-not $After.ContainsKey($key) -or $Before[$key] -ne $After[$key]) { throw 'workspace-changed' } }
}
function Invoke-JanitorTask([string]$Path, [int]$Days, [bool]$Delete, [datetime]$Now) {
    Assert-WorkspaceLock
    $record = New-JanitorRecord $Path
    $guard = $null; $tree = $null; $fresh = $null
    try {
        $path = Assert-JanitorChild $Path
        Assert-NoPendingRetirement $path
        $guard = New-Object HealthCheck.WorkspaceCleanup.Tree($false)
        $guard.PinAncestors([IO.Path]::GetDirectoryName($path))
        $tree = New-Object HealthCheck.WorkspaceCleanup.Tree($false)
        $tree.Scan($path, $script:EntryLimit)
        Test-JanitorMarkers @($tree.Entries | Where-Object { $null -eq $_.CacheRoot }) $path
        $state = Get-JanitorGitState $path $guard
        if ($state.Kind -ne 'clone') { throw 'shared-worktree-preserved' }
        $lifecycle=Get-LifecycleRecord $path
        Assert-LifecycleIdentity $path $lifecycle -Bound
        if ($lifecycle.State -cne 'completed') { throw 'lifecycle-not-completed' }
        $cacheProof = Get-JanitorCacheProof $tree $path
        Test-JanitorMarkers $tree.Entries $path
        $processes = Get-JanitorProcesses
        $record.HiddenProcessCommandLines = $processes.HiddenProcessCommandLines
        Test-JanitorProcess $path $processes
        $record.Git = $state.Kind
        Test-JanitorClean $path
        $age = [math]::Min((Get-JanitorAge $tree $path $Now), (Assert-LifecycleComplete $path $lifecycle $Now))
        $record.AgeDays = [math]::Round($age, 2)
        if ($age -lt $Days) { throw 'younger-than-retention' }
        $before = Get-JanitorSnapshot $tree $path
        $head = Get-JanitorGitText $path @('rev-parse', 'HEAD')
        # Explicit refspec; do not execute hooks, recurse into submodules or touch remote branches.
        [void](Get-JanitorGitText $path @('fetch', '--prune', '--no-tags', '--no-recurse-submodules', 'origin', '+refs/heads/*:refs/remotes/origin/*'))
        Test-JanitorClean $path
        Test-JanitorRefs $path
        $cacheProof = Get-JanitorCacheProof $tree $path
        if ((Get-JanitorGitText $path @('rev-parse', 'HEAD')) -ne $head) { throw 'workspace-changed' }
        $tree.Dispose(); $tree=$null
        $fresh = New-Object HealthCheck.WorkspaceCleanup.Tree($Delete -and $state.Kind -eq 'clone')
        $fresh.Scan($path, $script:EntryLimit)
        Set-JanitorCacheProof $fresh $cacheProof
        Test-JanitorMarkers $fresh.Entries $path
        Assert-JanitorSnapshot $before (Get-JanitorSnapshot $fresh $path)
        $processes = Get-JanitorProcesses
        $record.HiddenProcessCommandLines = $processes.HiddenProcessCommandLines
        Test-JanitorProcess $path $processes
        $record.Result='ELIGIBLE'; $record.Reason='clean-published-inactive'
        if (-not $Delete) { return $record }
        $relocation=Invoke-RetirementMove $path $lifecycle $fresh
        if ($relocation.State -eq 'NEEDS_REVIEW') { $record.Result='ERROR'; $record.Reason='retirement-needs-review-stop' }
        else { $record.Result='RETIRED'; $record.Reason='recoverably-retired' }
    } catch {
        $reason = [string]$_.Exception.Message
        $known = @('path-rejected','root-rejected','task-name-rejected','process-state-unknown','active-process',
            'private-runtime-marker','generated-cache-unproven','not-task-checkout','external-git-metadata','wrong-origin','remote-rewrite-or-unknown',
            'registration-unknown','dependent-worktrees','dirty-or-untracked','submodule-unknown','unknown-ignored-material',
            'age-unknown','younger-than-retention','unique-head-commit','ancestry-unknown','unknown-local-ref','unique-local-ref',
            'shared-worktree-preserved','lifecycle-unmanaged','lifecycle-invalid','lifecycle-identity-changed',
            'lifecycle-unbound','lifecycle-legacy-metadata','lifecycle-not-completed','lifecycle-head-changed',
            'retirement-pending','workspace-changed','git-check-failed','git-timeout','git-output-limit','delete-failed')
        $record.Reason = if ($known -contains $reason) { $reason } else { 'filesystem-or-check-unknown' }
        if ($record.Result -eq 'ELIGIBLE' -and $Delete) { $record.Result='ERROR'; $record.Reason='retirement-failed-stop' }
    } finally {
        foreach ($handle in @($fresh,$tree,$guard)) { if ($null -ne $handle) { $handle.Dispose() } }
    }
    return $record
}
function Save-JanitorReport($Report) {
    $pins = New-Object HealthCheck.WorkspaceCleanup.Tree($false)
    try {
        $pins.PinAncestors($script:LogDirectory)
        [HealthCheck.WorkspaceCleanup.Tree]::WriteSummary((Join-Path $script:LogDirectory 'workspace-cleanup-latest.json'), ($Report | ConvertTo-Json -Depth 5))
    } finally { $pins.Dispose() }
}
function Invoke-JanitorRun([string[]]$Roots, [int]$Days=7, [switch]$Delete) {
    Assert-WorkspaceLock
    if ($Days -lt 7) { throw 'retention-rejected' }
    $approved = @($Roots | ForEach-Object { Assert-JanitorRoot $_ } | Select-Object -Unique)
    if (-not $approved.Count) { throw 'root-rejected' }
    Initialize-JanitorNative
    $report = [pscustomobject]@{ Version=1; Mode=$(if ($Delete) {'Retire'} else {'DryRun'}); RetentionDays=$Days;
        Utc=[datetime]::UtcNow.ToString('o'); Records=@(); Status='complete' }
    # Fail before deletion if the bounded Ops summary cannot be safely written.
    Save-JanitorReport $report
    foreach ($rootPath in $approved) {
        $pin = New-Object HealthCheck.WorkspaceCleanup.Tree($false)
        try {
            $pin.PinAncestors($rootPath)
            $children = @([IO.Directory]::GetDirectories($rootPath) | Sort-Object)
            if ($children.Count -gt $script:TaskLimit) { throw 'task-limit' }
            foreach ($child in $children) {
                if ($report.Records.Count -ge $script:TaskLimit) { throw 'task-limit' }
                # Unsafe task names are opaque, never echo arbitrary directory names.
                try { [void](Assert-JanitorChild $child) } catch {
                    $report.Records += [pscustomobject]@{ Task='[rejected-name]'; Path=$rootPath; AgeDays=$null; Git='unknown'; Result='PRESERVE'; Reason='task-name-rejected' }
                    continue
                }
                $record = Invoke-JanitorTask $child $Days ([bool]$Delete) ([datetime]::UtcNow)
                $report.Records += $record
                Save-JanitorReport $report
                if ($record.Result -eq 'ERROR') { $report.Status='stopped'; break }
            }
        } catch {
            $report.Status='stopped'
            $report.Records += [pscustomobject]@{ Task='[root]'; Path=$rootPath; AgeDays=$null; Git='unknown'; Result='PRESERVE'; Reason='root-unavailable-or-limit' }
        } finally { $pin.Dispose() }
        if ($report.Status -eq 'stopped') { break }
    }
    Save-JanitorReport $report
    return $report
}
function Invoke-WorkspaceJanitor([string[]]$Roots, [int]$Days=7, [switch]$Delete) {
    Initialize-JanitorNative
    Invoke-WorkspaceLock { Invoke-JanitorRun $Roots $Days -Delete:$Delete }
}
# Container relocation, not snapshot/backup. No automatic recovery or purge.
function Get-RetirementFile([string]$Path) {
    Join-Path $script:LogDirectory ('workspace-retirement-'+[HealthCheck.WorkspaceCleanup.Tree]::StateKey($Path)+'.state')
}
function Get-RetirementKeys {
    @('Format','Transaction','Path','Destination','RootId','GitId','Enrollment','Owner','Claim','Generation','Head','Completed','BeforeDigest','AfterDigest','BeforeObservation','AfterObservation','Phase','Issue','NextClaim','NextGeneration')
}
function Write-RetirementJournal([string]$Path,$Journal,[switch]$Create) {
    Assert-WorkspaceLock
    $text=((Get-RetirementKeys|ForEach-Object {$_+'='+[string]$Journal[$_]}) -join "`n")+"`n"
    [HealthCheck.WorkspaceCleanup.Tree]::WriteState((Get-RetirementFile $Path),$text,[bool]$Create)
}
function Read-RetirementJournal([string]$Path) {
    Assert-WorkspaceLock
    $text=[HealthCheck.WorkspaceCleanup.Tree]::ReadState((Get-RetirementFile $Path))
    $keys=@(Get-RetirementKeys);$lines=$text.Split([char]10);$j=[ordered]@{}
    if($lines.Count -ne $keys.Count+1 -or $lines[-1] -cne ''){throw 'retirement-journal-invalid'}
    for($i=0;$i -lt $keys.Count;$i++){
        $prefix=$keys[$i]+'='
        if(-not $lines[$i].StartsWith($prefix,[StringComparison]::Ordinal)){throw 'retirement-journal-invalid'}
        $j[$keys[$i]]=$lines[$i].Substring($prefix.Length)
    }
    if($j.Format -cne '2' -or $j.Transaction -cnotmatch '^[a-f0-9]{32}$' -or
       $j.Path -cne [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Path.ToUpperInvariant())) -or
       $j.Destination -cne (Join-Path $script:RecoveryDirectory $j.Transaction).ToUpperInvariant() -or
       $j.RootId -cnotmatch '^\d+:\d+:\d+:\d+$' -or $j.GitId -cnotmatch '^\d+:\d+:\d+:\d+$' -or
       $j.Enrollment -cnotmatch '^[a-f0-9]{32}$' -or $j.Claim -cnotmatch '^[a-f0-9]{32}$' -or
       $j.Owner -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$' -or $j.Generation -cnotmatch '^[1-9][0-9]{0,8}$' -or
       $j.Head -cnotmatch '^([a-f0-9]{40}|[a-f0-9]{64})$' -or $j.Completed -cnotmatch '^[0-9]{18}$' -or
       $j.BeforeDigest -cnotmatch '^[A-F0-9]{64}$' -or $j.AfterDigest -cnotmatch '^(-|[A-F0-9]{64})$' -or
       $j.Phase -cnotmatch '^(prepared|retired|restore_prepared|restored|cancelled|needs_review)$' -or
       $j.Issue -cnotmatch '^[a-z-]{1,64}$' -or $j.NextClaim -cnotmatch '^(-|[a-f0-9]{32})$' -or
       $j.NextGeneration -cnotmatch '^(-|[1-9][0-9]{0,8})$'){throw 'retirement-journal-invalid'}
    foreach($key in @('BeforeObservation','AfterObservation')){
        if($j[$key] -cne '-' -and $j[$key] -cnotmatch ('^workspace-retirement-observation-'+$j.Transaction+'-[a-f0-9]{32}\.state$')){throw 'retirement-journal-invalid'}
    }
    if(($j.NextClaim -eq '-') -ne ($j.NextGeneration -eq '-')){throw 'retirement-journal-invalid'}
    if($j.NextClaim -ne '-' -and [int]$j.NextGeneration -ne ([int]$j.Generation+1)){throw 'retirement-journal-invalid'}
    if($j.Phase -in @('restore_prepared','restored','cancelled') -and $j.NextClaim -eq '-'){throw 'retirement-journal-invalid'}
    return $j
}
function Assert-NoPendingRetirement([string]$Path) {
    if([IO.File]::Exists((Get-RetirementFile $Path)) -or [IO.Directory]::Exists((Get-RetirementFile $Path))){
        $j=Read-RetirementJournal $Path
        if($j.Phase -notin @('restored','cancelled')){throw 'retirement-pending'}
        # A closed journal alone is not proof the fresh paused claim committed.
        # Later legitimate Resume/Complete cycles increment generation under this
        # same helper/mutex; an old completed record must never auto-retry.
        $r=Get-LifecycleRecord $Path
        foreach($key in @('Path','RootId','GitId','Enrollment','Owner')){if($r[$key] -cne $j[$key]){throw 'retirement-pending'}}
        if($r.Format -cne '1' -or $r.State -notin @('active','paused','completed') -or [int]$r.Generation -lt [int]$j.NextGeneration){throw 'retirement-pending'}
        if($r.Generation -ceq $j.NextGeneration -and ($r.Claim -cne $j.NextClaim -or $r.State -cne 'paused')){throw 'retirement-pending'}
    }
}
function Get-RetirementRows($Tree,[string]$Path) {
    @($Tree.Entries|ForEach-Object {
        $relative=$_.Path.Substring($Path.Length).ToUpperInvariant()
        $stamp=if($relative.Length){$_.Stamp}else{$_.Identity}
        [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($relative))+':'+$_.Directory+':'+$stamp
    }|Sort-Object -CaseSensitive)
}
function Get-RetirementDigest($Tree,[string]$Path) {
    $sha=[Security.Cryptography.SHA256]::Create()
    try{([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(((Get-RetirementRows $Tree $Path) -join "`n"))))).Replace('-','')}finally{$sha.Dispose()}
}
function Save-RetirementObservation($Tree,[string]$Location,$Journal,[string]$Stage,[string]$Issue='none') {
    $leaf='workspace-retirement-observation-'+$Journal.Transaction+'-'+[guid]::NewGuid().ToString('N')+'.state'
    $text="Format=1`nNonSnapshot=true`nStage=$Stage`nIssue=$Issue`nUtc=$([datetime]::UtcNow.ToString('o'))`nLocation=$([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Location)))`n"+((Get-RetirementRows $Tree $Location) -join "`n")+"`n"
    [HealthCheck.WorkspaceCleanup.Tree]::WriteObservation((Join-Path $script:LogDirectory $leaf),$text)
    return $leaf
}
function Get-RetirementInspection([string]$Location,$Journal,$Binding=$null) {
    Assert-WorkspaceLock
    $tree=New-Object HealthCheck.WorkspaceCleanup.Tree($false)
    $ownBinding=$false
    $out=[pscustomobject]@{Good=$false;Digest='-';Observation='-';Issue='inspection-incomplete'}
    try{
        if($null -eq $Binding){$Binding=New-Object HealthCheck.WorkspaceCleanup.Tree($true);$ownBinding=$true;$Binding.BindRootOnly($Location,$Journal.RootId)}
        $tree.ObserveBound($Binding,$Location,$Journal.RootId,$script:EntryLimit)
        $out.Digest=Get-RetirementDigest $tree $Location
        $out.Observation=Save-RetirementObservation $tree $Location $Journal 'post'
        if([HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($Location) -cne $Journal.RootId){$out.Issue='root-identity-changed';return $out}
        if($out.Digest -cne $Journal.BeforeDigest){$out.Issue='manifest-changed';return $out}
        if([HealthCheck.WorkspaceCleanup.Tree]::IdentityOf((Join-Path $Location '.git')) -cne $Journal.GitId){$out.Issue='git-identity-changed';return $out}
        $m=Read-LifecycleRecord (Join-Path $Location '.git\workspace-enrollment.state') -Marker
        foreach($k in @('Path','RootId','GitId','Enrollment')){if($m[$k] -cne $Journal[$k]){$out.Issue='enrollment-changed';return $out}}
        # A full matching metadata digest transfers the PRE-flight cache proof.
        # It is never an atomic content snapshot or permission to purge later.
        foreach($e in $tree.Entries){if($null -ne $e.CacheRoot){$tree.ApproveGeneratedCache($e.Path,$e.Stamp)}}
        Test-JanitorMarkers $tree.Entries $Location
        $out.Good=$true;$out.Issue='none'
    }catch{
        try{$out.Observation=Save-RetirementObservation $tree $Location $Journal 'partial' 'inspection-incomplete'}catch{}
    }finally{$tree.Dispose();if($ownBinding){$Binding.Dispose()}}
    return $out
}
function Set-RetirementReview([string]$Path,$Record,$Journal,[string]$Issue) {
    $Journal.Phase='needs_review';$Journal.Issue=$Issue
    Write-RetirementJournal $Path $Journal
    # Finish-return may have prepared a fresh paused claim before a failed write.
    # An uncertain return never grants it: retain the original retirement authority.
    foreach($key in @('Path','RootId','GitId','Enrollment','Owner','Claim','Generation','Head','Completed')){$Record[$key]=$Journal[$key]}
    $Record.Format='2';$Record.State='needs_review';$Record['Transaction']=$Journal.Transaction
    Write-LifecycleRecord $Path $Record
    return [pscustomobject]@{State='NEEDS_REVIEW';Transaction=$Journal.Transaction;Issue=$Issue}
}
function Complete-RetirementInspection([string]$Path,$Record,$Journal,[string]$Location,$Binding=$null) {
    $ownBinding=$false
    try{
    if($null -eq $Binding){$Binding=New-Object HealthCheck.WorkspaceCleanup.Tree($true);$ownBinding=$true;$Binding.BindRootOnly($Location,$Journal.RootId)}
    $inspection=Get-RetirementInspection $Location $Journal $Binding
    $Journal.AfterDigest=$inspection.Digest;$Journal.AfterObservation=$inspection.Observation
    if(-not $inspection.Good){return Set-RetirementReview $Path $Record $Journal $inspection.Issue}
    # Another object at the original path is never removed or overwritten.
    if($Location -cne $Path -and ([IO.Directory]::Exists($Path) -or [IO.File]::Exists($Path))){return Set-RetirementReview $Path $Record $Journal 'original-path-occupied'}
    $Journal.Phase='retired';$Journal.Issue='none';Write-RetirementJournal $Path $Journal
    $Record.Format='2';$Record.State='retired';$Record['Transaction']=$Journal.Transaction;Write-LifecycleRecord $Path $Record
    [pscustomobject]@{State='RETIRED';Transaction=$Journal.Transaction;Issue='none'}
    }catch{return Set-RetirementReview $Path $Record $Journal 'inspection-binding-unknown'}
    finally{if($ownBinding){$Binding.Dispose()}}
}
function Invoke-RetirementMove([string]$Path,$Record,$Tree) {
    Assert-WorkspaceLock
    $pins=New-Object HealthCheck.WorkspaceCleanup.Tree($false);$j=$null;$intent=$false
    try{
        $pins.PinAncestors($script:LogDirectory);$pins.PinAncestors($script:RecoveryDirectory)
        Assert-LifecycleIdentity $Path $Record -Bound
        $Tree.Freeze()
        $tx=[guid]::NewGuid().ToString('N')
        $j=[ordered]@{Format='2';Transaction=$tx;Path=$Record.Path;Destination=(Join-Path $script:RecoveryDirectory $tx).ToUpperInvariant();
            RootId=$Record.RootId;GitId=$Record.GitId;Enrollment=$Record.Enrollment;Owner=$Record.Owner;Claim=$Record.Claim;Generation=$Record.Generation;Head=$Record.Head;Completed=$Record.Completed;
            BeforeDigest=(Get-RetirementDigest $Tree $Path);AfterDigest='-';BeforeObservation='-';AfterObservation='-';Phase='prepared';Issue='none';NextClaim='-';NextGeneration='-'}
        $j.BeforeObservation=Save-RetirementObservation $Tree $Path $j 'pre'
        $file=Get-RetirementFile $Path
        if([IO.File]::Exists($file)){
            $old=Read-RetirementJournal $Path
            if($old.Phase -notin @('restored','cancelled')){throw 'retirement-pending'}
            [HealthCheck.WorkspaceCleanup.Tree]::WriteState((Join-Path $script:LogDirectory ('workspace-retirement-history-'+$old.Transaction+'.state')),[HealthCheck.WorkspaceCleanup.Tree]::ReadState($file),$true)
        }
        Write-RetirementJournal $Path $j;$intent=$true
        $Record.Format='2';$Record.State='retiring';$Record['Transaction']=$tx;Write-LifecycleRecord $Path $Record
        $Tree.ReleaseDescendantsForRelocation($j.RootId)
        $Tree.RenameTo($Path,$j.Destination)
        return Complete-RetirementInspection $Path $Record $j $j.Destination $Tree
    }catch{
        if($intent){return Set-RetirementReview $Path $Record $j 'operation-outcome-unknown'}
        throw
    }finally{$pins.Dispose()}
}
function Finish-RetirementReturn([string]$Path,$Record,$Journal,[string]$Phase,$Binding=$null) {
    $ownBinding=$false
    try{
    if($null -eq $Binding){$Binding=New-Object HealthCheck.WorkspaceCleanup.Tree($true);$ownBinding=$true;$Binding.BindRootOnly($Path,$Journal.RootId)}
    $inspection=Get-RetirementInspection $Path $Journal $Binding
    $Journal.AfterDigest=$inspection.Digest;$Journal.AfterObservation=$inspection.Observation
    if(-not $inspection.Good){return Set-RetirementReview $Path $Record $Journal $inspection.Issue}
    if([IO.Directory]::Exists($Journal.Destination) -or [IO.File]::Exists($Journal.Destination)){return Set-RetirementReview $Path $Record $Journal 'recovery-path-occupied'}
    if($Journal.NextClaim -eq '-'){
        if([int]$Record.Generation -ge 999999999){return Set-RetirementReview $Path $Record $Journal 'generation-exhausted'}
        $Journal.NextClaim=[guid]::NewGuid().ToString('N');$Journal.NextGeneration=([int]$Record.Generation+1).ToString()
    }
    $Journal.Phase=$Phase;$Journal.Issue='none';Write-RetirementJournal $Path $Journal
    $Record.Format='1';$Record.Remove('Transaction');$Record.State='paused';$Record.Claim=$Journal.NextClaim;$Record.Generation=$Journal.NextGeneration;$Record.Head='-';$Record.Completed='-'
    Write-LifecycleRecord $Path $Record
    return [pscustomobject]$Record
    }catch{return Set-RetirementReview $Path $Record $Journal 'return-binding-or-state-unknown'}
    finally{if($ownBinding){$Binding.Dispose()}}
}
function Invoke-RetirementRecovery([string]$Path,[string]$Owner,[string]$Token,[switch]$Restore) {
    Assert-WorkspaceLock
    $Path=Assert-JanitorChild $Path
    $guard=New-Object HealthCheck.WorkspaceCleanup.Tree($false);$tree=$null
    try{
        $guard.PinAncestors($script:LogDirectory);$guard.PinAncestors([IO.Path]::GetDirectoryName($Path));$guard.PinAncestors($script:RecoveryDirectory)
        $j=Read-RetirementJournal $Path;$r=Get-LifecycleRecord $Path
        if($Owner -cne $j.Owner -or $Token -cne $j.Claim){throw 'lifecycle-owner-or-claim-mismatch'}
        foreach($k in @('Path','RootId','GitId','Enrollment','Owner')){if($r[$k] -cne $j[$k]){throw 'retirement-record-mismatch'}}
        if($j.Phase -eq 'needs_review' -or $r.State -eq 'needs_review'){throw 'retirement-needs-review'}
        if($j.Phase -in @('restored','cancelled')){
            if($Restore){throw 'retirement-already-resolved'}
            if($r.Format -eq '1' -and $r.State -eq 'paused' -and $r.Claim -ceq $j.NextClaim -and $r.Generation -ceq $j.NextGeneration){return Finish-RetirementReturn $Path $r $j $j.Phase}
            if($r.Claim -cne $j.Claim -or $r.Generation -cne $j.Generation){throw 'retirement-record-mismatch'}
            return Finish-RetirementReturn $Path $r $j $j.Phase
        }
        if($r.Claim -cne $j.Claim -or $r.Generation -cne $j.Generation -or $r.Head -cne $j.Head -or $r.Completed -cne $j.Completed -or
           ($r.Format -eq '2' -and $r.Transaction -cne $j.Transaction)){throw 'retirement-record-mismatch'}
        $original=[IO.Directory]::Exists($Path) -or [IO.File]::Exists($Path)
        $recovery=[IO.Directory]::Exists($j.Destination) -or [IO.File]::Exists($j.Destination)
        if($original -eq $recovery){return Set-RetirementReview $Path $r $j 'locations-ambiguous'}
        if($original){
            if($Restore){throw 'retirement-not-in-recovery'}
            if($j.Phase -eq 'prepared'){return Finish-RetirementReturn $Path $r $j 'cancelled'}
            if($j.Phase -eq 'restore_prepared'){return Finish-RetirementReturn $Path $r $j 'restored'}
            return Set-RetirementReview $Path $r $j 'unexpected-original-location'
        }
        if($j.Phase -eq 'restore_prepared'){return Set-RetirementReview $Path $r $j 'restore-outcome-pending'}
        if(-not $Restore){return Complete-RetirementInspection $Path $r $j $j.Destination}
        if($r.Format -ne '2' -or $r.State -ne 'retired' -or $j.Phase -ne 'retired' -or [int]$r.Generation -ge 999999999){throw 'retirement-not-ready-to-restore'}
        $inspection=Get-RetirementInspection $j.Destination $j
        if(-not $inspection.Good){return Set-RetirementReview $Path $r $j $inspection.Issue}
        $tree=New-Object HealthCheck.WorkspaceCleanup.Tree($true);$tree.BindRootOnly($j.Destination,$j.RootId);$tree.Scan($j.Destination,$script:EntryLimit)
        if((Get-RetirementDigest $tree $j.Destination) -cne $j.BeforeDigest -or [HealthCheck.WorkspaceCleanup.Tree]::IdentityOf($j.Destination) -cne $j.RootId){return Set-RetirementReview $Path $r $j 'restore-preflight-changed'}
        # No blanket approval for changed cache data; matching metadata retains preflight proof.
        foreach($e in $tree.Entries){if($null -ne $e.CacheRoot){$tree.ApproveGeneratedCache($e.Path,$e.Stamp)}}
        $tree.Freeze()
        $j.NextClaim=[guid]::NewGuid().ToString('N');$j.NextGeneration=([int]$r.Generation+1).ToString();$j.Phase='restore_prepared';Write-RetirementJournal $Path $j
        $r.State='restoring';Write-LifecycleRecord $Path $r
        try{
            $tree.ReleaseDescendantsForRelocation($j.RootId);$tree.RenameTo($j.Destination,$Path)
            return Finish-RetirementReturn $Path $r $j 'restored' $tree
        }catch{return Set-RetirementReview $Path $r $j 'restore-outcome-unknown'}
    }finally{if($null -ne $tree){$tree.Dispose()};$guard.Dispose()}
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        Initialize-JanitorNative
        if ($Operation -ne 'Scan') {
            if ($Apply -or $Retire -or $PSBoundParameters.ContainsKey('Root') -or $PSBoundParameters.ContainsKey('RetentionDays')) { throw 'invalid-operation-options' }
            $operationResult=if ($Operation -in @('Recover','Restore')) {
                Invoke-WorkspaceLock { Invoke-RetirementRecovery $Workspace $Owner $ClaimId -Restore:($Operation -eq 'Restore') }
            } else { Invoke-WorkspaceLock { Invoke-WorkspaceLifecycle $Operation $Workspace $Owner $ClaimId } }
            $operationResult | ConvertTo-Json -Depth 5
        } else {
            if ($Apply) { throw 'permanent-delete-disabled-use-retire' }
            if ($Workspace -or $Owner -or $ClaimId) { throw 'invalid-operation-options' }
            $results = @(Invoke-WorkspaceJanitor $Root $RetentionDays -Delete:$Retire)
            foreach ($result in $results) { if ($result -is [string]) { Write-Output $result } else { $result | ConvertTo-Json -Depth 5 } }
            if ($results[-1].Status -ne 'complete') { exit 2 }
        }
    } catch { Write-Output '{"Status":"rejected","Reason":"configuration-state-or-log-unavailable"}'; exit 2 }
}
