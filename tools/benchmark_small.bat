@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo ========================================================
echo    LouLLabs STT - Benchmark (FAST model: "small")
echo ========================================================
echo.
echo  Compares the "small" model (lighter) against turbo.
echo  First launch: ~460 MB download, LET IT FINISH.
echo  Reuses your recordings: no need to speak again.
echo.
echo  At the end, copy the "LouLLabs Benchmark" results block.
echo ========================================================
echo.

py --version >nul 2>&1
if not errorlevel 1 (
    py "%~dp0benchmark.py" --repeats 5 --model small
    goto :end
)
python "%~dp0benchmark.py" --repeats 5 --model small

:end
echo.
echo ========================================================
echo   Done. Copy the "LouLLabs Benchmark" block above.
echo ========================================================
pause