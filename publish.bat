@echo off
cd /d C:\Users\brady\OneDrive\Desktop\nfl-tools

echo ============================
echo Updating NFL Dashboard...
echo ============================

echo.
echo Activating virtual environment...
call offseason_env\Scripts\activate

python --version
where python

echo.
echo Pulling latest changes...
git pull --rebase origin main
if errorlevel 1 goto :error

echo.
echo Running build script...
python build_tracker.py
if errorlevel 1 goto :error

echo.
echo Staging changes...
git add offseason/index.html
if errorlevel 1 goto :error

echo.
echo Committing changes...
git commit -m "Update offseason dashboard"
if errorlevel 1 goto :pushanyway

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

:pushanyway
echo.
echo Nothing new to commit, or commit step returned a non-zero code.
echo Attempting push anyway...
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