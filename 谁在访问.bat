@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo   ============================================================
echo    Who visited in the last 10 minutes
echo   ============================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$log = Join-Path '%~dp0' 'logs\agent.log';" ^
  "if (-not (Test-Path $log)) { Write-Host '  log not found'; exit }" ^
  "$since = (Get-Date).AddMinutes(-10);" ^
  "$dev = Select-String -Path $log -Pattern '\[DEVICE\]' -Encoding UTF8 | Where-Object { $_.Line -match '^\d{4}-\d{2}-\d{2} (\d{2}):(\d{2})' } | Select-Object -Last 40;" ^
  "Write-Host '  --- device-tagged requests ---';" ^
  "if ($dev) { $dev | ForEach-Object { Write-Host ('   ' + ($_.Line -replace '^.*\[DEVICE\] ','')) } } else { Write-Host '   (none yet)' }" ^
  "Write-Host '';" ^
  "Write-Host '  --- all client IPs seen ---';" ^
  "$ips = @{};" ^
  "Select-String -Path $log -Pattern '\[ACCESS\] (\d+\.\d+\.\d+\.\d+)' -Encoding UTF8 | ForEach-Object { if ($_.Line -match '\[ACCESS\] (\d+\.\d+\.\d+\.\d+)') { $k=$Matches[1]; $ips[$k] = 1 + $ips[$k] } };" ^
  "$ips.GetEnumerator() | Sort-Object Value -Descending | ForEach-Object { Write-Host ('   {0,-18} {1} requests' -f $_.Key, $_.Value) };" ^
  "Write-Host '';" ^
  "Write-Host '  --- this computer ---';" ^
  "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '10.*' } | ForEach-Object { Write-Host ('   ' + $_.InterfaceAlias + ' : ' + $_.IPAddress + ':' + $script:port) }"

echo.
echo   ============================================================
echo    Addresses to share
echo   ============================================================
echo.
for /f "usebackq delims=" %%u in ("public-url.txt") do set "PUB=%%u"
echo    Campus WiFi  : http://10.25.192.28:8765/
echo    4G / anywhere: !PUB!
echo.
pause
