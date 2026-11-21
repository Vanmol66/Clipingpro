@echo off
echo ============================================
echo   AI Video Clipper - Setup
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.9+
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check FFmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] FFmpeg not found in PATH.
    echo Download: https://ffmpeg.org/download.html
    echo The app will still work if ffmpeg is in a standard location.
    echo.
)

:: Install dependencies
echo Installing Python dependencies...
pip install -r requirements.txt
echo.

:: Create .env if not exists
if not exist .env (
    echo Creating .env file from template...
    copy .env.example .env
    echo [IMPORTANT] Edit .env and add your GEMINI_API_KEY
    echo Get a free key at: https://aistudio.google.com/apikey
    echo.
)

echo ============================================
echo   Setup complete! Run: python app.py
echo   Then open: http://localhost:5000
echo ============================================
pause
