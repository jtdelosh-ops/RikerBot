@echo off
setlocal

echo Creating Python virtual environment...
py -m venv .venv
if errorlevel 1 goto :error

call .venv\Scripts\activate.bat

echo Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist .env (
    copy .env.example .env >nul
    echo.
    echo Created .env from .env.example.
)

echo.
echo Setup complete.
echo Edit .env with your Discord token and IDs, then run run_windows.bat.
pause
exit /b 0

:error
echo.
echo Setup failed. Check that Python is installed and available through the "py" launcher.
pause
exit /b 1
