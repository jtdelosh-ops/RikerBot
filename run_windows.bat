@echo off
setlocal

if not exist .venv\Scripts\python.exe (
    echo Virtual environment not found.
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)

.venv\Scripts\python.exe bot.py
pause
