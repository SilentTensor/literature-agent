@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo   ============================================================
echo    CURRENT ADDRESSES
echo   ============================================================
echo.

for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  set "IP=%%a"
  set "IP=!IP: =!"
  echo    Campus wifi  : http://!IP!:8765/
)

if exist "public-url.txt" (
  set "PUB="
  for /f "usebackq delims=" %%u in ("public-url.txt") do set "PUB=%%u"
  echo    Public (any) : !PUB!
) else (
  echo    Public (any) : not available
)

echo.
echo   ============================================================
echo    RECENT VISITORS (last 40 requests)
echo   ============================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$log = Join-Path '%~dp0' 'logs\agent.log';" ^
  "if (Test-Path $log) {" ^
  "  Select-String -Path $log -Pattern '\[DEVICE\]' -Encoding UTF8 | Select-Object -Last 15 | ForEach-Object { Write-Host ('   ' + ($_.Line -replace '^.*\[DEVICE\] ','')) };" ^
  "  Write-Host '';" ^
  "  $ips=@{}; Select-String -Path $log -Pattern '\[ACCESS\] (\d+\.\d+\.\d+\.\d+)' -Encoding UTF8 | ForEach-Object { if ($_.Line -match '\[ACCESS\] (\d+\.\d+\.\d+\.\d+)') { $k=$Matches[1]; $ips[$k]=1+$ips[$k] } };" ^
  "  $ips.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 8 | ForEach-Object { Write-Host ('   {0,-18} {1} requests' -f $_.Key, $_.Value) }" ^
  "} else { Write-Host '   log not found' }"
echo.
pause
