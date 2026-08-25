@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title LouLLabs STT - Build .exe

echo ========================================================
echo    LouLLabs STT - BUILD the app (.exe)
echo ========================================================
echo.
echo   This creates a single .exe that you double-click to RUN the app.
echo   (Run install.bat first if you haven't installed the dependencies yet.)
echo.

REM --- Guard: refuse to run from inside a ZIP (files would be missing) ---
if not exist "%~dp0loullabs_stt.py" (
    echo [!] Please EXTRACT the archive first, then run build.bat from the extracted folder.
    echo.
    pause
    exit /b 1
)

REM --- Find Python ---
set "PY="
py --version >nul 2>&1 && set "PY=py"
if not defined PY ( python --version >nul 2>&1 && set "PY=python" )
if not defined PY (
    echo [ERROR] Python was not found. Install Python 3.10+ from https://python.org
    echo         and check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM --- Make sure dependencies are present (they are needed to build) ---
%PY% -c "import PySide6, faster_whisper, sounddevice, numpy, pyperclip" >nul 2>&1
if errorlevel 1 (
    echo [!] Dependencies are missing. Please run install.bat first, then build.bat.
    echo.
    pause
    exit /b 1
)

echo Installing the build tool ^(PyInstaller^) if needed...
%PY% -m pip install pyinstaller >nul 2>&1

echo.
echo Building the .exe - this can take a few minutes, please wait...
echo.
REM One-file build, written straight to this folder (the "." keeps it at the root).
%PY% -m PyInstaller --noconfirm --distpath "%~dp0." LouLLabs_STT.spec
if errorlevel 1 (
    echo.
    echo [ERROR] The build failed.
    pause
    exit /b 1
)

REM Tidy up the temporary build cache so only the .exe remains.
if exist "%~dp0build" rmdir /s /q "%~dp0build"

echo.
echo ========================================================
echo   SUCCESS - your app is ready at the root of this folder:
echo   %~dp0LouLLabs_STT.exe
echo ========================================================
echo.
echo   Double-click LouLLabs_STT.exe to run the app (it lives in the system tray).
echo   You can also move or pin that single file anywhere you like.
echo.
start "" explorer "%~dp0"
pause
