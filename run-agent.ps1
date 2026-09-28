# ===================================================================
#  Literature Survey Agent - launcher (called by Scheduled Task / VBS)
#
#  NOTE: this file is deliberately ASCII-only. Windows PowerShell 5.1
#  decodes .ps1 files as the system ANSI codepage (GBK on zh-CN) unless
#  they carry a UTF-8 BOM, so non-ASCII text here would corrupt parsing.
#  Runtime output (which IS UTF-8) is redirected to the log file instead.
#
#  Usage:
#    powershell -NoProfile -ExecutionPolicy Bypass -File run-agent.ps1
# ===================================================================

$ErrorActionPreference = "Continue"

$Root    = $PSScriptRoot
$App     = Join-Path $Root "app.py"
$VenvPy  = Join-Path $Root ".venv\Scripts\python.exe"
$Python  = if (Test-Path $VenvPy) { $VenvPy } else { "python" }
$LogDir  = Join-Path $Root "logs"
$LogFile = Join-Path $LogDir "agent.log"
$Port    = if ($env:PORT) { $env:PORT } else { "8765" }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log($msg) {
    Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" -Encoding UTF8
}

function Rotate-Log {
    if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 5MB)) {
        Move-Item -Force $LogFile (Join-Path $LogDir "agent.log.1")
    }
}

Rotate-Log
Write-Log "========== starting Literature Survey Agent on port $Port =========="
Write-Log "python = $Python"
Write-Log "app    = $App"

if (-not (Test-Path $App)) {
    Write-Log "ERROR: app.py not found, aborting."
    exit 1
}

# If the port is already taken, exit now; the Scheduled Task restart policy
# will retry in a couple of minutes.
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Log "port $Port already in use by PID $(($busy | Select-Object -ExpandProperty OwningProcess) -join ','), aborting."
    exit 1
}

$env:PORT = $Port
# Let app.py open the log file itself (see LOG_FILE handling in app.py).
# This keeps the log UTF-8 correct AND readable while the service runs,
# which piping through PowerShell's redirection would not.
$env:LOG_FILE = $LogFile

Set-Location $Root

try {
    # Foreground: the Scheduled Task owns the lifetime. app.py tees its own
    # stdout/stderr into $LogFile, so nothing is captured by this pipeline.
    & $Python $App
    $code = $LASTEXITCODE
    Write-Log "service exited with code $code."
    Rotate-Log
    exit $code
} catch {
    Write-Log "service crashed: $($_.Exception.Message)"
    exit 1
}
