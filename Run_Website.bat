@echo off
cd /d "%~dp0"
echo Installing required Python packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Could not install the required packages. Check your internet connection.
  pause
  exit /b 1
)
echo.
echo Starting LabMarket website...
python app.py
pause
