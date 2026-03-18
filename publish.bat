@echo off
cd /d C:\Users\brady\OneDrive\Desktop\nfl-tools

echo ============================
echo Updating NFL Dashboard...
echo ============================

echo.
echo Activating virtual environment...
call C:\Users\brady\OneDrive\Desktop\nfl-tools\offseason_env\Scripts\activate

echo.
echo Pulling latest changes...
git pull --rebase origin main
if errorlevel 1 goto :error

echo.
echo Running build script...
python build_tracker.py
if errorlevel 1 goto :error

echo.
echo Staging files...
git add offseason/index.html
git add publish.bat
git add -u
if errorlevel 1 goto :error

echo.
echo Committing changes...
git diff --cached --quiet
if %errorlevel%==0 goto :nocommit

git commit -m "Update offseason dashboard"
if errorlevel 1 goto :error

:nocommit
echo.
echo Pushing to GitHub...
git push
if errorlevel 1 goto :error

echo.
echo ============================
echo DONE! Site updating now.
echo ============================
pause
exit /b 0

:error
echo.
echo ============================
echo ERROR: publish failed.
echo ============================
pause
exit /b 1