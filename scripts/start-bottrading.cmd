@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-bottrading.ps1"
exit /b %ERRORLEVEL%
