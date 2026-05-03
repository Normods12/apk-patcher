@echo off
setlocal

set "BASE_DIR=%~dp0"
set "SCRIPT=%BASE_DIR%telegram_processor.py"

echo Starting Telegram Automation Pipeline...
python "%SCRIPT%"

echo.
echo Completed.
pause
