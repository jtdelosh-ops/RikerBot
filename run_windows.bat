@echo off
setlocal EnableExtensions EnableDelayedExpansion

if not exist .venv\Scripts\python.exe (
    echo Virtual environment not found.
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)

rem 1Password is optional. Use it only when a local .env.op file exists;
rem otherwise preserve the standard .env workflow.
if exist .env.op (
    set "OP_COMMAND=op"
    where op >nul 2>&1
    if errorlevel 1 (
        if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\op.exe" (
            set "OP_COMMAND=%LOCALAPPDATA%\Microsoft\WinGet\Links\op.exe"
        ) else (
            echo 1Password CLI was not found.
            echo Install it to use .env.op, or remove .env.op and use .env normally.
            pause
            exit /b 1
        )
    )

    echo Loading RikerBot secrets from 1Password...
    !OP_COMMAND! run --env-file=.env.op -- .venv\Scripts\python.exe bot.py
) else (
    .venv\Scripts\python.exe bot.py
)
pause
