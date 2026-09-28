# ===================================================================
#  Literature Survey Agent - tunnel watchdog
#
#  Ensures the public tunnel (Cloudflare quick tunnel, run by
#  tunnel_manager.py) is alive and the public URL actually answers.
#  If not, restart it and refresh public-url.txt.
#
#  The service itself has its own watchdog; this one only cares about
#  the public link.
#
#  ASCII-only on purpose (Windows PowerShell 5.1 decodes .ps1 as the
#  system ANSI codepage unless the file has a UTF-8 BOM).
# ===================================================================

$ErrorActionPreference = "Continue"

$Root    = $PSScriptRoot
$LogDir  = Join-Path $Root "logs"
$LogFile = Join-Path $LogDir "tunnel-watchdog.log"
$UrlFile = Join-Path $Root "public-url.txt"
$Port    = if ($env:PORT) { $env:PORT } else { "8765" }
$VenvPy  = Join-Path $Root ".venv\Scripts\python.exe"
$Manager = Join-Path $Root "tunnel_manager.py"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log($msg) {
    Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" -Encoding UTF8
}

if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 1MB)) {
    Move-Item -Force $LogFile (Join-Path $LogDir "tunnel-watchdog.log.1")
}

# 1) Is the tunnel process alive? (python running tunnel_manager.py)
$proc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match "tunnel_manager\.py" }

# 2) Does the public URL actually answer?
$url = ""
if (Test-Path $UrlFile) { $url = (Get-Content $UrlFile -Raw).Trim() }
$urlOk = $false
if ($url -match "^https?://") {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 25 -Uri "$url/api/health" `
             -Headers @{ "User-Agent" = "Mozilla/5.0" }
        $urlOk = ($r.StatusCode -eq 200)
    } catch { $urlOk = $false }
}

if ($proc -and $urlOk) { exit 0 }   # healthy

if (-not $proc) {
    Write-Log "tunnel process not running - starting it"
} else {
    Write-Log "tunnel process alive but $url did not answer - restarting"
}

# Clear out a broken tunnel: python manager, cloudflared, and any legacy
# localtunnel leftovers from the previous implementation.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match "tunnel_manager\.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match "tunnel-runner|localtunnel" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3

# Make sure the local service is up before publishing it
try {
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 6 -Uri "http://127.0.0.1:$Port/api/health" | Out-Null
} catch {
    Write-Log "local service not answering - starting it via watchdog.ps1"
    $wd = Join-Path $Root "watchdog.ps1"
    if (Test-Path $wd) { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wd | Out-Null }
    Start-Sleep -Seconds 12
}

# Start the tunnel manager detached from this script
$py = if (Test-Path $VenvPy) { $VenvPy } else { "python" }
if (-not (Test-Path $Manager)) {
    Write-Log "ERROR: tunnel_manager.py not found at $Manager"
    exit 1
}
Write-Log "launching tunnel_manager.py"
Start-Process -FilePath $py -ArgumentList "`"$Manager`"", $Port, "`"$Root`"" `
    -WorkingDirectory $Root -WindowStyle Hidden

# Wait for a fresh URL, then confirm it works
$newUrl = ""
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 5
    if (Test-Path $UrlFile) {
        $c = (Get-Content $UrlFile -Raw).Trim()
        if ($c -match "^https?://") { $newUrl = $c; break }
    }
}

if (-not $newUrl) {
    Write-Log "WARNING: no URL written after restart"
    exit 1
}

for ($i = 0; $i -lt 8; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 25 -Uri "$newUrl/api/health" `
             -Headers @{ "User-Agent" = "Mozilla/5.0" }
        if ($r.StatusCode -eq 200) {
            Write-Log "tunnel OK, public url = $newUrl"
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 6
}

Write-Log "WARNING: tunnel restarted but $newUrl still not answering"
exit 1
