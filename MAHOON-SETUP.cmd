@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0local-tools\mahoon-local.ps1" -Mode Setup
set "MAHOON_EXIT=%ERRORLEVEL%"
if not "%MAHOON_NONINTERACTIVE%"=="1" pause
exit /b %MAHOON_EXIT%
