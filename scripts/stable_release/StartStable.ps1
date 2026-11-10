# Compatible with Windows PowerShell 5.1 and PowerShell 7. Used by legacy autostart.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Binding)
$ErrorActionPreference = 'Stop'
$b = Get-Content -LiteralPath $Binding -Raw -Encoding UTF8 | ConvertFrom-Json
$python = Join-Path $b.code '.venv\Scripts\python.exe'
$runner = Join-Path $PSScriptRoot 'ui_server.py'
$receipt = Join-Path (Split-Path -Parent $Binding) $b.receipt
if (Test-Path -LiteralPath $receipt) { throw 'Fresh UI binding required' }
if (@([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
      Where-Object Port -eq $b.port).Count) { throw 'UI port occupied' }
# The Python launcher uses hidden processes and null output handles, preventing
# inherited console/transcript pipes from retaining or logging service output.
& $python -I -B $runner --launch $Binding
if ($LASTEXITCODE -ne 0) { throw 'UI startup failed' }
