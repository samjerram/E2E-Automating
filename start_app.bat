@echo off
REM P2NNI CSV Upload – double-click to start. Keep this window open; close it to stop.
REM First run: sets up venv and installs dependencies (may take a few minutes).

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python 3 from python.org and try again.
    pause
    exit /b 1
)

if not exist venv\Scripts\activate.bat (
    echo.
    echo First run: the app needs to install dependencies (Python packages and a browser).
    echo This may take a few minutes. You only need to do this once.
    echo.
    set /p answer="Install now? (y/n) "
    if /i "%answer%"=="y" goto do_install
    if /i "%answer%"=="yes" goto do_install
    echo Skipped. Run this again and choose y when ready, or see HOW_TO_START.txt for manual setup.
    pause
    exit /b 0
    :do_install
    echo Setting up...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
    playwright install chromium
    echo Setup complete. Starting app...
) else (
    call venv\Scripts\activate.bat
)

python app.py
if errorlevel 1 pause
