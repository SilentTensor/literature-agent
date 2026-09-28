# ===================================================================
#  Literature Survey Agent - public tunnel launcher
#
#  Publishes the local service (port 8765) on a public https URL using
#  localtunnel. No account, no credit card, no server required.
#
#  The current address is always written to  public-url.txt  in the
#  project root by tunnel-runner.js.
#
#  ASCII-only on purpose (Windows PowerShell 5.1 decodes .ps1 as the
#  system ANSI codepage unless the file has a UTF-8 BOM).
# ===================================================================

$ErrorActionPreference = "Continue"

$Root    = $PSScriptRoot
$LogDir  = Join-Path $Root "logs"
$LogFile = Join-Path $LogDir "tunnel.log"
$UrlFile = Join-Path $Root "public-url.txt"
$Runner  = Join-Path $Root "tunnel-runner.js"
$Port    = if ($env:PORT) { $env:PORT } else { "8765" }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log($msg) {
    Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" -Encoding UTF8
}

if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 2MB)) {
    Move-Item -Force $LogFile (Join-Path $LogDir "tunnel.log.1")
}

Write-Log "========== tunnel requested for port $Port =========="

# --- locate node -----------------------------------------------------
$Node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
if (-not $Node) { $Node = (Get-Command node -ErrorAction SilentlyContinue).Source }
if (-not $Node) {
    Write-Log "ERROR: node.js not found. Install it from https://nodejs.org and retry."
    exit 1
}

# --- make sure the local service is up -------------------------------
$localUp = $false
for ($i = 0; $i -lt 15; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 6 -Uri "http://127.0.0.1:$Port/api/health"
        if ($r.StatusCode -eq 200) { $localUp = $true; break }
    } catch { }
    Start-Sleep -Seconds 3
}
if (-not $localUp) {
    Write-Log "local service not responding - asking the watchdog to start it"
    $wd = Join-Path $Root "watchdog.ps1"
    if (Test-Path $wd) { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wd | Out-Null }
    Start-Sleep -Seconds 15
}

# --- stop any previous tunnel so we never run two ---------------------
Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match "tunnel-runner\.js" } |
    ForEach-Object {
        Write-Log "stopping previous tunnel PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2

# --- install localtunnel once ----------------------------------------
$ltDir = Join-Path $LogDir "node_modules\localtunnel"
if (-not (Test-Path $ltDir)) {
    Write-Log "installing localtunnel (one-off, a few seconds) ..."
    Push-Location $LogDir
    & npm install localtunnel --no-audit --no-fund --loglevel=error 2>&1 |
        Add-Content -LiteralPath $LogFile -Encoding UTF8
    Pop-Location
    if (-not (Test-Path $ltDir)) {
        Write-Log "WARNING: localtunnel install failed - check the log above and your network."
    }
}

# --- run it, restarting forever if it dies ---------------------------
$attempt = 0
while ($true) {
    $attempt++
    Write-Log "starting tunnel-runner (attempt $attempt)"

    try {
        # NODE_PATH lets the runner resolve localtunnel from logs\node_modules
        $env:NODE_PATH = Join-Path $LogDir "node_modules"
        Push-Location $LogDir
        & $Node $Runner $Port $UrlFile $LogFile
        Pop-Location
        Write-Log "tunnel-runner exited with code $LASTEXITCODE"
    } catch {
        Write-Log "tunnel-runner crashed: $($_.Exception.Message)"
    }

    Write-Log "restarting in 10 seconds ..."
    Start-Sleep -Seconds 10
}
