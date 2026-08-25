@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo ========================================================
echo        LouLLabs STT - Benchmark
echo ========================================================
echo.
echo  Au 1er lancement, le modele Whisper (~1.5 Go) se
echo  telecharge : une barre de progression apparait,
echo  LAISSEZ-LA FINIR (plusieurs minutes).
echo.
echo  A la fin, un bloc de resultats s'affiche : copiez-le.
echo ========================================================
echo.

py --version >nul 2>&1
if not errorlevel 1 (
    py tools\benchmark.py --repeats 5
    goto :end
)
python tools\benchmark.py --repeats 5

:end
echo.
echo ========================================================
echo   Termine. Copiez le bloc "LouLLabs Benchmark" ci-dessus
echo   (ou le fichier tools\benchmark_data\result_*.json).
echo ========================================================
pause
