function Get-ValidProcessId {
    param([object]$Value)

    if ($null -eq $Value) { return $null }
    try { $processId = [int]$Value } catch { return $null }
    if ($processId -le 0) { return $null }
    return $processId
}

function Get-ProcessSnapshot {
    $processes = @()
    $errors = @()
    try {
        $rawProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    } catch {
        return [pscustomobject]@{
            Processes = @()
            Errors = @("process snapshot query failed: $($_.Exception.Message)")
        }
    }
    foreach ($rawProcess in $rawProcesses) {
        if ($null -eq $rawProcess) {
            $errors += "process snapshot contained a null record"
            continue
        }
        $processId = Get-ValidProcessId $rawProcess.ProcessId
        if ($null -eq $processId) {
            $errors += "process snapshot contained a record without a valid PID"
            continue
        }
        $parentId = Get-ValidProcessId $rawProcess.ParentProcessId
        if ($null -eq $parentId) {
            $errors += "process $processId has no valid parent PID"
        }
        $processes += [pscustomobject]@{
            Id = $processId
            ParentId = $parentId
            Name = [string]$rawProcess.Name
            CommandLine = [string]$rawProcess.CommandLine
        }
    }
    return [pscustomobject]@{
        Processes = @($processes)
        Errors = @($errors)
    }
}

function Get-OwnedProcessSnapshot {
    param(
        [int]$RootId,
        [object[]]$Snapshot
    )

    $errors = @()
    $byId = @{}
    $byParent = @{}
    foreach ($process in @($Snapshot)) {
        if ($null -eq $process) {
            $errors += "owned-process snapshot contained a null record"
            continue
        }
        $processId = Get-ValidProcessId $process.Id
        if ($null -eq $processId) {
            $errors += "owned-process snapshot contained a record without a valid PID"
            continue
        }
        if ($byId.ContainsKey($processId)) {
            $errors += "process snapshot contained duplicate PID $processId"
            continue
        }
        $byId.Add($processId, $process)
        $parentId = Get-ValidProcessId $process.ParentId
        if ($null -eq $parentId) {
            $errors += "process $processId has no usable parent relation"
            continue
        }
        if (-not $byParent.ContainsKey($parentId)) {
            $byParent.Add($parentId, [System.Collections.ArrayList]::new())
        }
        [void]$byParent[$parentId].Add($process)
    }

    $owned = @()
    $seen = [System.Collections.Generic.HashSet[int]]::new()
    $pending = [System.Collections.Generic.Queue[int]]::new()
    $rootProcessId = Get-ValidProcessId $RootId
    if ($null -eq $rootProcessId) {
        $errors += "harness root PID is invalid"
    } else {
        $pending.Enqueue($rootProcessId)
        if ($byId.ContainsKey($rootProcessId)) {
            [void]$seen.Add($rootProcessId)
            $owned += $byId[$rootProcessId]
        } elseif (@($Snapshot).Count -gt 0) {
            $errors += "harness root PID $rootProcessId is absent from a non-empty process snapshot"
        }
    }

    while ($pending.Count -gt 0) {
        $parentId = $pending.Dequeue()
        if (-not $byParent.ContainsKey($parentId)) { continue }
        foreach ($child in @($byParent[$parentId])) {
            $childId = Get-ValidProcessId $child.Id
            if ($null -eq $childId) {
                $errors += "owned-process leaf has no valid PID"
                continue
            }
            if ($seen.Add($childId)) {
                $owned += $child
                $pending.Enqueue($childId)
            }
        }
    }
    return [pscustomobject]@{
        Processes = @($owned | Sort-Object Id -Unique)
        Errors = @($errors)
    }
}

function Stop-OwnedProcesses {
    param([object[]]$Owned)

    $terminated = @()
    $identityChanged = @()
    $errors = @()
    foreach ($candidate in @($Owned | Sort-Object @{Expression = { $_.Id }; Descending = $true})) {
        $candidateId = Get-ValidProcessId $candidate.Id
        if ($null -eq $candidateId) {
            $errors += "cleanup candidate has no valid PID"
            continue
        }
        try {
            $current = Get-CimInstance Win32_Process -Filter "ProcessId=$candidateId" -ErrorAction Stop
        } catch {
            $errors += "could not establish identity for PID $candidateId`: $($_.Exception.Message)"
            continue
        }
        if ($null -eq $current) { continue }
        if ([string]$current.Name -ne [string]$candidate.Name -or
            [string]$current.CommandLine -ne [string]$candidate.CommandLine) {
            $identityChanged += $candidateId
            continue
        }
        try {
            Stop-Process -Id $candidateId -Force -ErrorAction Stop
            $terminated += $candidateId
        } catch {
            $errors += "could not stop verified PID $candidateId`: $($_.Exception.Message)"
        }
    }
    return [pscustomobject]@{
        TerminatedProcessIds = @($terminated | Sort-Object -Unique)
        IdentityChangedProcessIds = @($identityChanged | Sort-Object -Unique)
        Errors = @($errors)
    }
}
