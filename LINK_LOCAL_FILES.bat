@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\link_local_files.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\link_local_files.ps1" -BuildTools "%~1"
)
if errorlevel 1 (
  echo.
  echo Local files were not linked. Read the error above.
  pause
  exit /b 1
)

echo.
echo Build tools are ready. Nothing large was copied.
pause
