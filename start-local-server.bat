@echo off
setlocal

cd /d "%~dp0"
set "PORT=8787"

echo Starting SYDRRO-TECH local server...
echo The browser will open automatically.
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    py sydrro-local-server.py %PORT% --open
    goto :eof
)

where python >nul 2>nul
if %errorlevel%==0 (
    python sydrro-local-server.py %PORT% --open
    goto :eof
)

where python3 >nul 2>nul
if %errorlevel%==0 (
    python3 sydrro-local-server.py %PORT% --open
    goto :eof
)

echo Python was not found. Install Python, then run this file again.
pause
