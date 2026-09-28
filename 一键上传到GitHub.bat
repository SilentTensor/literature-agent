@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Literature Agent - upload to GitHub
echo   (Chinese guide: see the .md file in this folder)
echo ============================================================
echo.

:ask_user
set "GHUSER="
set /p GHUSER=Type your GitHub username then press Enter:
if "%GHUSER%"=="" (
  echo   Empty input, please try again.
  goto ask_user
)

set "REPO=literature-agent"
set "REMOTE=https://github.com/%GHUSER%/%REPO%.git"

echo.
echo   Target: %REMOTE%
echo.
echo   BEFORE continuing, do this in your browser:
echo     1) Open https://github.com/new
echo     2) Repository name: %REPO%
echo     3) Public or Private, either is fine
echo     4) Do NOT tick "Add a README file"
echo     5) Click the green "Create repository" button
echo.
pause

echo.
echo [1/3] Saving local changes...
git add -A
git -c user.name="Literature Agent" -c user.email="agent@example.com" commit -q -m "update" 2>nul
echo       done

echo [2/3] Setting remote...
git remote remove origin 2>nul
git remote add origin "%REMOTE%"
echo       done

echo [3/3] Uploading...
echo.
echo       If a login window appears, choose "Sign in with your browser"
echo       and click Authorize in the browser.
echo.
rem --force: GitHub may already hold an auto-generated README, or an older
rem version of this project, with no shared history with the local repo,
rem which makes a normal push get rejected. This folder is the authoritative
rem copy, so overwriting the remote branch is intended.
git push --force -u origin main
if errorlevel 1 goto failed

echo.
echo ============================================================
echo   UPLOAD OK
echo.
echo   Next: deploy at https://render.com
echo   Detailed steps (Chinese): see the .md guide in this folder
echo ============================================================
echo.
pause
exit /b 0

:failed
echo.
echo ============================================================
echo   UPLOAD FAILED. Common causes:
echo     - wrong GitHub username
echo       check https://github.com/settings/profile
echo     - the repository was not created on GitHub yet (redo step 1)
echo     - cannot reach GitHub from this network
echo   Send a screenshot of the red text above to get help.
echo ============================================================
echo.
pause
exit /b 1
