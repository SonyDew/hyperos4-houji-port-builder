@echo off
setlocal
cd /d "%~dp0"
title HyperOS 4 port builder for houji

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed or is missing from PATH.
  echo Install Python 3.11 or newer, then try again.
  pause
  exit /b 1
)

if "%~1"=="" (
  python build_port_update.py
) else (
  python build_port_update.py "%~1"
)

if errorlevel 1 (
  echo.
  echo The build stopped. Read the last error above.
  pause
  exit /b 1
)

echo.
echo Done. The update ZIP is in the output folder.
pause
exit /b 0
