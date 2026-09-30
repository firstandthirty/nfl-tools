@echo off
setlocal
cd /d "%~dp0\.."

py -m injury_tracker.scripts.update_week --config injury_tracker\config\current_week.json
if errorlevel 1 (
  echo Week update failed.
  pause
  exit /b 1
)

echo Week update complete.
pause
