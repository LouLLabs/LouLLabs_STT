@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

py --version >nul 2>&1
if not errorlevel 1 (
    py loullabs_stt.py
    goto :end
)

python loullabs_stt.py

:end
echo.
echo Programme termine.
pause
