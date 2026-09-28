@echo off
setlocal
cd /d "%~dp0"

set "URLFILE=public-url.txt"

if not exist "%URLFILE%" (
  echo.
  echo   No public URL yet - the tunnel is probably still starting.
  echo   Waiting 25 seconds, then trying again...
  echo.
  start "" wscript.exe "tunnel-hidden.vbs"
  timeout /t 25 >nul
)

set "URL="
for /f "usebackq delims=" %%u in ("%URLFILE%") do set "URL=%%u"

if "%URL%"=="" (
  echo.
  echo   Still no public URL. Check logs\tunnel.log for details.
  echo.
  pause
  exit /b 1
)

echo.
echo   ============================================================
echo    PUBLIC ADDRESS - works on 4G, from other cities, anywhere
echo.
echo      %URL%
echo.
echo   ============================================================
echo    Opening it in your browser...
echo.
echo    Notes:
echo      - No warning page: phones can open this link directly.
echo      - This address CHANGES if the tunnel reconnects.
echo        Just run this file again to get the newest one.
echo      - Works only while this computer is switched on.
echo      - On the SAME campus wifi, this one is faster:
echo          http://10.25.192.28:8765/
echo.

start "" "%URL%"
echo   (Copy the address above before closing this window.)
timeout /t 40 >nul
