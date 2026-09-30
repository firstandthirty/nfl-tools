@echo off
setlocal
cd /d "%~dp0\.."

py -m injury_tracker.scripts.review_app --config injury_tracker\config\current_week.json
if errorlevel 1 (
  echo Review app failed.
  pause
  exit /b 1
)

pause
