[CmdletBinding()]
param(
    [string]$UiUrl = "http://127.0.0.1:8000",
    [string]$IngestUrl,
    [double]$Timeout = 3
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$env:UV_CACHE_DIR = Join-Path $repoRoot ".uv-cache"
$arguments = @(
    "run", "python", "-m", "healthcheck.cli", "smoke",
    "--ui-url", $UiUrl,
    "--timeout", "$Timeout"
)
if ($IngestUrl) {
    $arguments += @("--ingest-url", $IngestUrl)
}

Push-Location $repoRoot
try {
    & uv @arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
