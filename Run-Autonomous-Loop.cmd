@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo .venv bulunamadi. Once Build-Windows-EXE.cmd calistirin.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m src.growth_os.autonomous_daemon --site turkiye-gundemi --status published --publish-site --enrich-images
pause
