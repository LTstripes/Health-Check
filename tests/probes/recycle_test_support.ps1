# Shared synthetic harness hygiene and flushed evidence; not a production helper.
$script:RecycleTestSupportPath=$PSCommandPath
function Assert-RecycleProbeHost {
    if($PSVersionTable.PSEdition -ne 'Desktop' -or $PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'Synthetic harness requires Windows PowerShell5.1'}
}
function New-RecycleProbeRoot([string]$TempBase) {
    $base=[IO.Path]::GetFullPath($TempBase).TrimEnd('\')
    $configuredTemp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    if($base -ine $configuredTemp -and [IO.Path]::GetFileName($base) -inotmatch '^(tmp|temp)$'){throw 'Existing temp base required'}
    $drive=[IO.Path]::GetPathRoot($base)
    if($drive.Length -ne 3 -or $drive[1] -ne ':' -or $drive[2] -ne [char]92){throw 'Local temp drive required'}
    $current=$base
    while($current){
        $item=Get-Item -LiteralPath $current -Force -ErrorAction Stop
        if(-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Name -ieq '.git'){throw 'Temp ancestor rejected'}
        $current=if($item.Parent){$item.Parent.FullName}else{$null}
    }
    $nonce=[guid]::NewGuid().ToString('N')
    $root=Join-Path $base ('healthcheck-recycle-tests-'+$nonce)
    if(Test-Path -LiteralPath $root){throw 'New harness root collision;no adoption'}
    [void][IO.Directory]::CreateDirectory($root)
    $marker=Join-Path $root '.harness-owned'
    $stream=[IO.File]::Open($marker,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {$bytes=[Text.Encoding]::UTF8.GetBytes('WorkspaceRecycleSyntheticOnly:'+$nonce);$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
    return $root
}
function Write-RecycleProbeEvidence($Receipt,[string]$Path) {
    $Receipt['support_sha256']=(Get-FileHash -LiteralPath $script:RecycleTestSupportPath -Algorithm SHA256).Hash
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Receipt|ConvertTo-Json -Depth 10))
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    try {$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}
