@echo off
setlocal
cd /d "%~dp0\.."

set /p SEASON=Season [2026]: 
if "%SEASON%"=="" set SEASON=2026
set /p WEEK=Week: 
if "%WEEK%"=="" (
  echo Week is required.
  pause
  exit /b 1
)

py -c "import json; from pathlib import Path; p=Path('injury_tracker/config/current_week.json'); p.write_text(json.dumps({'season': int('%SEASON%'), 'week': int('%WEEK%')}, indent=2) + '\n', encoding='utf-8'); print('Current injury tracker week set to %SEASON% Week %WEEK%')"
if errorlevel 1 (
  echo Failed to update current week config.
  pause
  exit /b 1
)

pause
