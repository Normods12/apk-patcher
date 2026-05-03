@echo off
setlocal

set "BASE_DIR=%~dp0"
set "SCRIPT=%BASE_DIR%replace_last_dex.py"

if not exist "%BASE_DIR%output-apks" mkdir "%BASE_DIR%output-apks"
if not exist "%BASE_DIR%input-apks" mkdir "%BASE_DIR%input-apks"
if not exist "%BASE_DIR%dex-to-add" mkdir "%BASE_DIR%dex-to-add"

python "%SCRIPT%" ^
  --payload-dex "%BASE_DIR%Dex-to-add\classes.dex" ^
  --input-dir "%BASE_DIR%Input-apk" ^
  --output-dir "%BASE_DIR%Output-apk" ^
  --clean-output

echo.
echo Completed.
pause
