# ===================================================================
#  Literature Survey Agent - watchdog / ensure-running
#
#  Registered as a Scheduled Task that repeats every 5 minutes (and at
#  logon). If the service is not answering on its port, it starts it.
#  This is what makes the agent survive a crash, a kill, or a reboot:
#  the Scheduled Task's own "restart on failure" policy does NOT fire
#  when the child process is killed externally, a watchdog does.
#
#  ASCII-only on purpose (Windows PowerShell 5.1 decodes .ps1 as the
#  system ANSI codepage unless the file has a UTF-8 BOM).
# ===================================================================

$ErrorActionPreference = "Continue"

$Root    = $PSScriptRoot
$App     = Join-Path $Root "app.py"
$VenvPy  = Join-Path $Root ".venv\Scripts\python.exe"
$Python  = if (Test-Path $VenvPy) { $VenvPy } else { "python" }
$Vbs     = Join-Path $Root "run-agent-hidden.vbs"
$LogDir  = Join-Path $Root "logs"
$LogFile = Join-Path $LogDir "watchdog.log"
$Port    = if ($env:PORT) { $env:PORT } else { "8765" }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log($msg) {
    Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" -Encoding UTF8
}

if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 2MB)) {
    Move-Item -Force $LogFile (Join-Path $LogDir "watchdog.log.1")
}

function Test-Agent {
    # Prefer a real HTTP probe: it proves the app serves requests, not just
    # that something holds the socket.
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 -Uri "http://127.0.0.1:$Port/api/health"
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

if (Test-Agent) {
    exit 0
}

# Not answering. Is the port held by a half-dead process? If so, clear it.
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    $pids = $busy | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pids) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -match '^(python|pythonw)$') {
            Write-Log "port $Port held by unresponsive python PID $procId - terminating it."
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 3
}

if (-not (Test-Path $App)) {
    Write-Log "ERROR: app.py not found at $App - cannot start."
    exit 1
}

Write-Log "agent is not responding on port $Port - starting it."

if (Test-Path $Vbs) {
    Start-Process -FilePath "wscript.exe" -ArgumentList "`"$Vbs`"" -WorkingDirectory $Root
} else {
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$(Join-Path $Root 'run-agent.ps1')`"" `
        -WorkingDirectory $Root -WindowStyle Hidden
}

# Give it a moment and confirm; report if it still failed.
Start-Sleep -Seconds 20
if (Test-Agent) {
    Write-Log "start OK."
    exit 0
}

Write-Log "WARNING: agent still not responding 20s after start attempt."
exit 1
