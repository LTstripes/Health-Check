function ConvertTo-ProcessId {
    param([object]$Value)

    if ($null -eq $Value) { return $null }
    try { $processId = [int]$Value } catch { return $null }
    if ($processId -le 0) { return $null }
    return $processId
}

function Test-CapturedProcessIdentity {
    param([object]$Identity)

    $validId = $null -ne (ConvertTo-ProcessId $Identity.Id)
    $hasName = -not [string]::IsNullOrWhiteSpace([string]$Identity.Name)
    $hasCommandLine = -not [string]::IsNullOrWhiteSpace([string]$Identity.CommandLine)
    $hasCreationTime = [string]$Identity.CreationTime -match '^[1-9][0-9]*$'
    return ($validId -and $hasName -and $hasCommandLine -and $hasCreationTime)
}

function Test-SameProcessIdentity {
    param(
        [object]$Expected,
        [object]$Actual
    )

    $sameId = (ConvertTo-ProcessId $Expected.Id) -eq (ConvertTo-ProcessId $Actual.Id)
    $sameName = [string]$Expected.Name -eq [string]$Actual.Name
    $sameCommandLine = [string]$Expected.CommandLine -eq [string]$Actual.CommandLine
    $sameCreationTime = [string]$Expected.CreationTime -eq [string]$Actual.CreationTime
    return ((Test-CapturedProcessIdentity $Expected) -and
        (Test-CapturedProcessIdentity $Actual) -and $sameId -and $sameName -and $sameCommandLine -and $sameCreationTime)
}

function Get-ProcessIdentity {
    param([object]$ProcessId)

    $validProcessId = ConvertTo-ProcessId $ProcessId
    if ($null -eq $validProcessId) {
        return [pscustomobject]@{
            Id = $null
            Name = ""
            CommandLine = ""
            Exists = $false
            QueryError = "process identity PID is invalid"
        }
    }
    try {
        $matches = @(Get-CimInstance Win32_Process -Filter "ProcessId=$validProcessId" -ErrorAction Stop)
    } catch {
        return [pscustomobject]@{
            Id = $validProcessId
            Name = ""
            CommandLine = ""
            Exists = $false
            QueryError = "could not establish identity for PID $validProcessId`: $($_.Exception.Message)"
        }
    }
    if ($matches.Count -eq 0) {
        return [pscustomobject]@{
            Id = $validProcessId
            Name = ""
            CommandLine = ""
            Exists = $false
            QueryError = $null
        }
    }
    if ($matches.Count -ne 1) {
        return [pscustomobject]@{
            Id = $validProcessId
            Name = ""
            CommandLine = ""
            Exists = $false
            QueryError = "process identity PID $validProcessId is ambiguous"
        }
    }
    $match = $matches[0]
    return [pscustomobject]@{
        Id = $validProcessId
        Name = [string]$match.Name
        CommandLine = [string]$match.CommandLine
        CreationTime = if ($match.CreationDate) { $match.CreationDate.ToUniversalTime().Ticks.ToString() } else { "" }
        Exists = $true
        QueryError = $null
    }
}

function Assert-ExternalRuntimePath {
    param(
        [string]$RepoRoot,
        [string]$RuntimeRoot
    )

    $resolvedRuntime = [IO.Path]::GetFullPath($RuntimeRoot)
    $repoPrefix = $RepoRoot.TrimEnd('\') + '\'
    if ($resolvedRuntime.Equals($RepoRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $resolvedRuntime.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "synthetic runtime path must be outside the checkout: $resolvedRuntime"
    }
    return $resolvedRuntime
}

function Get-OwnedProcessTree {
    param([object]$CapturedIdentity)

    # One coherent ancestry snapshot; never infer ownership from a process name.
    $snapshot = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $root = @($snapshot | Where-Object { $_.ProcessId -eq $CapturedIdentity.Id })
    if ($root.Count -ne 1) { throw "root absent or ambiguous in ownership snapshot" }
    $owned = @()
    $pending = @($root[0])
    while ($pending.Count -gt 0) {
        $row = $pending[0]
        $pending = @($pending | Select-Object -Skip 1)
        if (@($owned | Where-Object { $_.Id -eq $row.ProcessId }).Count -gt 0) {
            throw "cyclic or duplicate process ownership"
        }
        $identity = [pscustomobject]@{
            Id = [int]$row.ProcessId
            Name = [string]$row.Name
            CommandLine = [string]$row.CommandLine
            CreationTime = if ($row.CreationDate) { $row.CreationDate.ToUniversalTime().Ticks.ToString() } else { "" }
        }
        if (-not (Test-CapturedProcessIdentity $identity)) { throw "owned process identity incomplete" }
        if ($owned.Count -eq 0 -and -not (Test-SameProcessIdentity $CapturedIdentity $identity)) {
            throw "root identity changed in ownership snapshot"
        }
        $owned += $identity
        $children = @($snapshot | Where-Object { $_.ParentProcessId -eq $row.ProcessId })
        foreach ($child in $children) {
            if (-not $child.CreationDate -or $child.CreationDate -lt $row.CreationDate) {
                throw "ambiguous descendant ownership (reused parent PID)"
            }
        }
        $pending += $children
    }
    return $owned
}

function Test-Exit255LifecycleTranscript {
    param([object[]]$OutputLines, [object[]]$OwnedProcessIds)

    # Exact, case-sensitive English grammar (one output item = one whole line):
    # transcript := (SUCCESS | ERROR Reason)+, with at least one ERROR.
    # PID/parent := [1-9][0-9]*. No blank lines, trimming or embedded CR/LF.
    # Each owned PID has exactly one record; no other PID may have a record.
    $successPattern = '\ASUCCESS: The process with PID ([1-9][0-9]*) \(child process of PID ([1-9][0-9]*)\) has been terminated\.\z'
    $errorPattern = '\AERROR: The process with PID ([1-9][0-9]*) \(child process of PID ([1-9][0-9]*)\) could not be terminated\.\z'
    $reason = "Reason: There is no running instance of the task."
    $expected = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($processId in $OwnedProcessIds) {
        if (-not $expected.Add([string]$processId)) { return $false }
    }
    if ($expected.Count -eq 0) { return $false }
    $reported = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $errorCount = 0
    $index = 0
    while ($index -lt $OutputLines.Count) {
        if ($OutputLines[$index] -isnot [string]) { return $false }
        $record = [regex]::Match($OutputLines[$index], $successPattern)
        if ($record.Success) {
            $index++
        } else {
            $record = [regex]::Match($OutputLines[$index], $errorPattern)
            if (-not $record.Success -or $index + 1 -ge $OutputLines.Count -or
                $OutputLines[$index + 1] -isnot [string] -or $OutputLines[$index + 1] -cne $reason) {
                return $false
            }
            $errorCount++
            $index += 2
        }
        $reportedId = $record.Groups[1].Value
        if (-not $expected.Contains($reportedId) -or -not $reported.Add($reportedId)) { return $false }
    }
    return ($errorCount -gt 0 -and $reported.SetEquals($expected))
}

function Invoke-RootProcessTreeTermination {
    param([object]$CapturedIdentity, [int]$PostTimeoutSeconds = 5)

    $identityChanged = @()
    $errors = @()
    $terminationIssued = $false
    $rootAlreadyExited = $false
    $owned = @()
    $remaining = @()
    $taskkillExit = $null
    $taskkillOutput = @()
    $lifecycleDiagnostic = $false
    $outcome = "failed"
    if (-not (Test-CapturedProcessIdentity $CapturedIdentity)) {
        $errors += "captured root identity is incomplete"
    } else {
        $current = Get-ProcessIdentity $CapturedIdentity.Id
        if ($current.QueryError) {
            $errors += [string]$current.QueryError
        } elseif (-not $current.Exists) {
            $rootAlreadyExited = $true
            $errors += "root exited before ownership snapshot; descendant cleanup is unproven"
        } elseif (-not (Test-SameProcessIdentity $CapturedIdentity $current)) {
            $identityChanged += [int]$CapturedIdentity.Id
            $errors += "root PID $($CapturedIdentity.Id) identity changed before tree cleanup"
        } else {
            try {
                $owned = @(Get-OwnedProcessTree $CapturedIdentity)
                $preKill = Get-ProcessIdentity $CapturedIdentity.Id
                if ($preKill.QueryError -or -not (Test-SameProcessIdentity $CapturedIdentity $preKill) -or -not $preKill.Exists) {
                    throw "root identity unavailable or changed immediately before termination"
                }
                $terminationIssued = $true # issued, not a claim of native success
                $taskkillOutput = @(& taskkill.exe /PID ([string]$CapturedIdentity.Id) /T /F 2>&1 | ForEach-Object { [string]$_ })
                $taskkillExit = $LASTEXITCODE
                $lifecycleDiagnostic = Test-Exit255LifecycleTranscript $taskkillOutput @($owned.Id)
                $deadline = [DateTime]::UtcNow.AddSeconds($PostTimeoutSeconds)
                do {
                    $remaining = @()
                    foreach ($identity in $owned) {
                        $post = Get-ProcessIdentity $identity.Id
                        if ($post.QueryError) {
                            $errors += [string]$post.QueryError
                        } elseif ($post.Exists) {
                            if (Test-SameProcessIdentity $identity $post) { $remaining += [int]$identity.Id }
                            else { $identityChanged += [int]$identity.Id }
                        }
                    }
                    if ($remaining.Count -eq 0 -or $errors.Count -gt 0 -or $identityChanged.Count -gt 0) { break }
                    if ([DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 100 }
                } while ([DateTime]::UtcNow -lt $deadline)
                if ($remaining.Count -gt 0) { $errors += "owned process survived root-tree termination" }
                if ($identityChanged.Count -gt 0) { $errors += "owned process identity changed during termination" }
                if ($taskkillExit -eq 0 -and $errors.Count -eq 0) {
                    $outcome = "terminated"
                } elseif ($taskkillExit -eq 255 -and $errors.Count -eq 0 -and $lifecycleDiagnostic) {
                    # Reconcile only a verified, fully absent tree. Ports/runtime
                    # are separate mandatory caller postconditions. No second kill.
                    $outcome = "exited-during-termination"
                } else {
                    $errors += "root process-tree termination failed with exit code $taskkillExit"
                }
            } catch {
                $errors += $_.Exception.Message
            }
        }
    }
    return [pscustomobject]@{
        TerminationIssued = $terminationIssued
        RootAlreadyExited = $rootAlreadyExited
        Outcome = $outcome
        TaskkillExitCode = $taskkillExit
        TaskkillOutput = @($taskkillOutput)
        LifecycleDiagnosticVerified = $lifecycleDiagnostic
        OwnedProcessIdentities = @($owned)
        RemainingOwnedProcessIds = @($remaining)
        IdentityChangedProcessIds = @($identityChanged)
        Errors = @($errors)
    }
}

function Get-LoopbackPortEvidence {
    param([int]$Port)

    $listener = $null
    try {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return [pscustomobject]@{ Closed = $true; Error = $null }
    } catch {
        $socketError = $_.Exception
        $isAddressInUse = $false
        while ($null -ne $socketError) {
            if ($socketError -is [Net.Sockets.SocketException] -and
                $socketError.SocketErrorCode -eq [Net.Sockets.SocketError]::AddressAlreadyInUse) {
                $isAddressInUse = $true
                break
            }
            $socketError = $socketError.InnerException
        }
        if ($isAddressInUse) {
            return [pscustomobject]@{ Closed = $false; Error = $null }
        }
        return [pscustomobject]@{ Closed = $false; Error = "loopback port $Port bind probe failed: $($_.Exception.Message)" }
    } finally {
        if ($null -ne $listener) {
            try {
                $listener.Stop()
            } catch {
            }
        }
    }
}
