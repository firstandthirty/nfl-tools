@echo off
setlocal
cd /d "%~dp0\.."

for /f "delims=" %%R in ('git rev-parse --show-toplevel 2^>nul') do set "REPO_ROOT=%%R"
if not defined REPO_ROOT (
  echo Could not locate the git repository root.
  pause
  exit /b 1
)

cd /d "%REPO_ROOT%"

py -m injury_tracker.scripts.publish_to_github --config injury_tracker\config\current_week.json
if errorlevel 1 (
  echo GitHub publish failed. Review the message above before retrying.
  pause
  exit /b 1
)

echo GitHub publish complete.
pause
