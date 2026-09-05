[CmdletBinding()]
param(
    [string]$DataDir,
    [int]$Port = 8120,
    [switch]$EnableIngest,
    [string]$IngestHost = "127.0.0.1",
    [int]$IngestPort = 8121
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$env:UV_CACHE_DIR = Join-Path $repoRoot ".uv-cache"

if (-not $DataDir) {
    if ($env:HEALTHCHECK_DATA_DIR) {
        $DataDir = $env:HEALTHCHECK_DATA_DIR
    } elseif ($env:LOCALAPPDATA) {
        $DataDir = Join-Path $env:LOCALAPPDATA "Health-Check"
    } else {
        $DataDir = Join-Path ([Environment]::GetFolderPath("UserProfile")) "AppData\Local\Health-Check"
    }
}

$runtimeRoot = [IO.Path]::GetFullPath($DataDir)
$repoPrefix = $repoRoot.TrimEnd('\') + '\'
if ($runtimeRoot.Equals($repoRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $runtimeRoot.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "HEALTHCHECK_DATA_DIR must be outside the checkout: $runtimeRoot"
}

$env:HEALTHCHECK_DATA_DIR = $runtimeRoot
$env:HEALTHCHECK_UI_PORT = "$Port"
$env:HEALTHCHECK_INGEST_HOST = $IngestHost
$env:HEALTHCHECK_INGEST_PORT = "$IngestPort"

& uv run python -m healthcheck.cli prepare-runtime
if ($LASTEXITCODE -ne 0) { throw "Runtime directory preparation failed with exit code $LASTEXITCODE" }

& uv run python -m healthcheck.cli migrate
if ($LASTEXITCODE -ne 0) { throw "Runtime migration preparation failed with exit code $LASTEXITCODE" }

$ingestProcess = $null
try {
    if ($EnableIngest) {
        $ingestProcess = Start-Process -FilePath "uv" `
            -ArgumentList @("run", "python", "-m", "healthcheck.cli", "serve", "--app", "ingest") `
            -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
    }

    & uv run python -m healthcheck.cli serve --app ui
    if ($LASTEXITCODE -ne 0) { throw "Loopback server stopped with exit code $LASTEXITCODE" }
} finally {
    if ($ingestProcess -and -not $ingestProcess.HasExited) {
        Stop-Process -Id $ingestProcess.Id -Force
    }
}
