@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo ========================================================
echo        Compilation - LouLLabs STT (.exe)
echo ========================================================
echo.

REM S'assurer que PyInstaller est installe
py -m pip install pyinstaller >nul 2>&1 || python -m pip install pyinstaller >nul 2>&1

REM Compilation depuis le fichier .spec (icone + assets inclus)
py -m PyInstaller --noconfirm LouLLabs_STT.spec
if errorlevel 1 (
    python -m PyInstaller --noconfirm LouLLabs_STT.spec
)

echo.
if errorlevel 1 (
    echo [ERREUR] La compilation a echoue.
    pause
    exit /b 1
)
echo ========================================================
echo   Termine ! Executable : dist\LouLLabs_STT\LouLLabs_STT.exe
echo   (Le modele Whisper se telecharge au 1er lancement.)
echo ========================================================
echo.
pause
