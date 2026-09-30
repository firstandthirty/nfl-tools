@echo off
setlocal
cd /d "%~dp0\.."

py -m injury_tracker.scripts.build_public_site --config injury_tracker\config\current_week.json
if errorlevel 1 (
  echo Public site build failed.
  pause
  exit /b 1
)

echo Public site build complete.
pause
