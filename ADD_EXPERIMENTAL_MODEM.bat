@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  echo Drag the experimental modem IMG or ZIP onto this file.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\import_experimental_modem.ps1" -Source "%~1"
if errorlevel 1 (
  echo.
  echo The modem was not imported. Read the error above.
  pause
  exit /b 1
)

echo.
echo Ready. Future first-install packages will offer the experimental modem on non-CN devices.
pause
