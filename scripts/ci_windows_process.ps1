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
    return ($validId -and $hasName -and $hasCommandLine)
}

function Test-SameProcessIdentity {
    param(
        [object]$Expected,
        [object]$Actual
    )

    $sameId = (ConvertTo-ProcessId $Expected.Id) -eq (ConvertTo-ProcessId $Actual.Id)
    $sameName = [string]$Expected.Name -eq [string]$Actual.Name
    $sameCommandLine = [string]$Expected.CommandLine -eq [string]$Actual.CommandLine
    return ((Test-CapturedProcessIdentity $Expected) -and
        (Test-CapturedProcessIdentity $Actual) -and $sameId -and $sameName -and $sameCommandLine)
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

function Invoke-RootProcessTreeTermination {
    param([object]$CapturedIdentity)

    $identityChanged = @()
    $errors = @()
    $terminationIssued = $false
    $rootAlreadyExited = $false
    if (-not (Test-CapturedProcessIdentity $CapturedIdentity)) {
        $errors += "captured root identity is incomplete"
    } else {
        $current = Get-ProcessIdentity $CapturedIdentity.Id
        if ($current.QueryError) {
            $errors += [string]$current.QueryError
        } elseif (-not $current.Exists) {
            $rootAlreadyExited = $true
        } elseif (-not (Test-SameProcessIdentity $CapturedIdentity $current)) {
            $identityChanged += [int]$CapturedIdentity.Id
            $errors += "root PID $($CapturedIdentity.Id) identity changed before tree cleanup"
        } else {
            & taskkill.exe /PID ([string]$CapturedIdentity.Id) /T /F 2>&1 | Out-Null
            $taskkillExit = $LASTEXITCODE
            if ($taskkillExit -ne 0) {
                $errors += "root process-tree termination failed with exit code $taskkillExit"
            } else {
                $terminationIssued = $true
            }
        }
    }
    return [pscustomobject]@{
        TerminationIssued = $terminationIssued
        RootAlreadyExited = $rootAlreadyExited
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
