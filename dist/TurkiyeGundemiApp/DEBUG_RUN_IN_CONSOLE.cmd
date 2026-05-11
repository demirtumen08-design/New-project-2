@echo off
setlocal
cd /d "%~dp0"
echo Starting TurkiyeGundemiApp from:
echo %CD%
echo.
"%~dp0TurkiyeGundemiApp.exe"
echo.
echo Exit code: %ERRORLEVEL%
pause
