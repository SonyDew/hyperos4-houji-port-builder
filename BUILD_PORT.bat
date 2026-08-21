@echo off
setlocal
cd /d "%~dp0"
title HyperOS 4 port builder for Xiaomi 14

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer was not found in PATH.
  pause
  exit /b 1
)

if "%~1"=="" (
  python build_port.py
) else if "%~2"=="" (
  echo Drag both official OTA ZIPs onto this file, or put them in the input folder.
  pause
  exit /b 1
) else if "%~3"=="" (
  python build_port.py "%~1" "%~2"
) else (
  python build_port.py "%~1" "%~2" --experimental-modem "%~3"
)

if errorlevel 1 (
  echo.
  echo The build stopped. Read the last error above.
  pause
  exit /b 1
)

echo.
echo Done. The first-install and no-wipe update packages are in output.
pause
