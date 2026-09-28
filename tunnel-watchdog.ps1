# ===================================================================
#  Literature Survey Agent - tunnel watchdog
#
#  The service already has a watchdog; the tunnel needs one too.
#  If the public URL stops answering, restart the tunnel and rewrite
#  public-url.txt with the (possibly new) address.
#
#  Runs every 5 minutes via Scheduled Task. ASCII-only on purpose.
# ===================================================================

$ErrorActionPreference = "Continue"

$Root    = $PSScriptRoot
$LogDir  = Join-Path $Root "logs"
$LogFile = Join-Path $LogDir "tunnel-watchdog.log"
$UrlFile = Join-Path $Root "public-url.txt"
$Port    = if ($env:PORT) { $env:PORT } else { "8765" }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log($msg) {
    Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" -Encoding UTF8
}

if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 1MB)) {
    Move-Item -Force $LogFile (Join-Path $LogDir "tunnel-watchdog.log.1")
}

# --- is the tunnel process alive? ------------------------------------
$proc = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match "tunnel-runner" }

# --- is the public URL actually answering? ---------------------------
$url = ""
if (Test-Path $UrlFile) { $url = (Get-Content $UrlFile -Raw).Trim() }
$urlOk = $false
if ($url -match "^https?://") {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 -Uri "$url/api/health" `
             -Headers @{ "User-Agent" = "Mozilla/5.0" }
        $urlOk = ($r.StatusCode -eq 200)
    } catch { $urlOk = $false }
}

if ($proc -and $urlOk) { exit 0 }   # everything healthy, do nothing

if (-not $proc) {
    Write-Log "tunnel process is not running - restarting"
} else {
    Write-Log "tunnel process alive (PID $($proc.ProcessId -join ',')) but $url did not answer - restarting"
    foreach ($p in $proc) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
}

# Make sure the local service is up first
try {
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 6 -Uri "http://127.0.0.1:$Port/api/health" | Out-Null
} catch {
    Write-Log "local service not answering - starting it via watchdog.ps1"
    $wd = Join-Path $Root "watchdog.ps1"
    if (Test-Path $wd) { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wd | Out-Null }
    Start-Sleep -Seconds 12
}

# Start the tunnel through the hidden VBS launcher (no console window)
$vbs = Join-Path $Root "tunnel-hidden.vbs"
if (Test-Path $vbs) {
    Start-Process -FilePath "wscript.exe" -ArgumentList "`"$vbs`"" -WorkingDirectory $Root
} else {
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$(Join-Path $Root 'tunnel.ps1')`"" `
        -WorkingDirectory $Root -WindowStyle Hidden
}

# Wait for a fresh URL to appear, then confirm it works
$newUrl = ""
for ($i = 0; $i -lt 12; $i++) {
    Start-Sleep -Seconds 5
    if (Test-Path $UrlFile) {
        $candidate = (Get-Content $UrlFile -Raw).Trim()
        if ($candidate -match "^https?://") { $newUrl = $candidate; break }
    }
}

if (-not $newUrl) {
    Write-Log "WARNING: no URL written after restart attempt"
    exit 1
}

for ($i = 0; $i -lt 6; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 -Uri "$newUrl/api/health" `
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
