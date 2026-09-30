@echo off
setlocal
cd /d "%~dp0\.."

py -m injury_tracker.scripts.publish_public_site --config injury_tracker\config\current_week.json
if errorlevel 1 (
  echo Publish preparation failed.
  pause
  exit /b 1
)

echo Publish preparation complete. Review git status before committing.
pause
