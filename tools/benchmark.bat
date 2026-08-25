@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo ========================================================
echo    LouLLabs STT - Benchmark (ACCURATE model: "turbo")
echo ========================================================
echo.
echo  Measures the "large-v3-turbo" model (max quality) on CPU,
echo  all cores, 5 repetitions.
echo  First launch: ~1.6 GB download, LET IT FINISH.
echo  Reuses your recordings: no need to speak again.
echo.
echo  At the end, copy the "LouLLabs Benchmark" results block.
echo ========================================================
echo.

py --version >nul 2>&1
if not errorlevel 1 (
    py "%~dp0benchmark.py" --repeats 5 --model large-v3-turbo
    goto :end
)
python "%~dp0benchmark.py" --repeats 5 --model large-v3-turbo

:end
echo.
echo ========================================================
echo   Done. Copy the "LouLLabs Benchmark" block above.
echo ========================================================
pause
