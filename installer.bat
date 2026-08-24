@echo off
chcp 65001 >nul 2>&1
echo.
echo ========================================================
echo        Installation - LouLLabs STT (Speech to Text)
echo ========================================================
echo.

REM Essayer "py" (Python Launcher), puis "python"
py --version >nul 2>&1
if not errorlevel 1 (
    echo Python detecte via py :
    py --version
    echo.
    echo Installation des dependances...
    echo.
    py -m pip install -r "%~dp0requirements.txt"
    goto :done
)

python --version >nul 2>&1
if not errorlevel 1 (
    echo Python detecte via python :
    python --version
    echo.
    echo Installation des dependances...
    echo.
    python -m pip install -r "%~dp0requirements.txt"
    goto :done
)

echo [ERREUR] Python n'est pas trouve.
echo.
echo Installez Python depuis https://python.org
echo et cochez "Add Python to PATH" pendant l'installation.
echo.
pause
exit /b 1

:done
echo.
if errorlevel 1 (
    echo [ERREUR] Probleme pendant l'installation.
    pause
    exit /b 1
)
echo ========================================================
echo   Installation terminee !
echo.
echo   Pour lancer  : double-cliquez sur lancer.bat
echo   Pour compiler: double-cliquez sur build.bat
echo   1er lancement = telechargement du modele (~1.5 Go)
echo ========================================================
echo.
pause
