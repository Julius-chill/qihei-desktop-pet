@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW="
for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do if not defined PYTHONW set "PYTHONW=%%P"

if not defined PYTHONW (
    echo ERROR: pythonw.exe not found>"%~dp0launcher.log"
    echo Python 3 was not found. See launcher.log.
    pause
    exit /b 1
)

echo Starting with %PYTHONW%>"%~dp0launcher.log"
start "" /b "%PYTHONW%" "%~dp0pet.py" 1>>"%~dp0launcher.log" 2>&1
if errorlevel 1 (
    echo Launch failed. See launcher.log.
    pause
    exit /b 1
)
endlocal
