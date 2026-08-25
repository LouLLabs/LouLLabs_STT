@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title LouLLabs STT - Install

echo ========================================================
echo    LouLLabs STT - INSTALL (dependencies only)
echo ========================================================
echo.
echo   This installs what the app needs. It does NOT launch the app.
echo   Next step: run build.bat to create the app (.exe), then run that .exe.
echo.

REM --- Guard: refuse to run from inside a ZIP (files would be missing) ---
if not exist "%~dp0requirements.txt" (
    echo [!] Please EXTRACT the archive first, then run install.bat from the extracted folder.
    echo.
    pause
    exit /b 1
)

REM --- Find Python (py launcher first, then python) ---
set "PY="
py --version >nul 2>&1 && set "PY=py"
if not defined PY ( python --version >nul 2>&1 && set "PY=python" )
if not defined PY (
    echo [ERROR] Python was not found.
    echo Install Python 3.10+ from https://python.org
    echo and check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo Installing dependencies, please wait...
echo.
%PY% -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo [ERROR] Installation failed. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo   Setup complete!
echo   Next: run build.bat to create the app (LouLLabs_STT.exe).
echo ========================================================
echo.
pause
