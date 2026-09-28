@echo off
setlocal
cd /d "%~dp0"

set "URLFILE=public-url.txt"

if not exist "%URLFILE%" (
  echo.
  echo   Public URL file not found.
  echo   The tunnel may not be running. Starting it now, please wait ~20s and retry.
  echo.
  start "" wscript.exe "tunnel-hidden.vbs"
  timeout /t 20 >nul
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
echo    Current public address:
echo.
echo      %URL%
echo.
echo    ============================================================
echo    Opening it in your browser...
echo.
echo    Notes:
echo      - This address CHANGES when the tunnel reconnects.
echo        Just run this file again to see the newest one.
echo      - It only works while this computer is switched on.
echo      - For people on the SAME campus wifi, the LAN address is
echo        usually faster - see README.
echo.

start "" "%URL%"
echo   (You can close this window; the address above is copyable.)
timeout /t 30 >nul
