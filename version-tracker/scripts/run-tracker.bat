@echo off
REM Run the tracker from the repository root
cd /d "%~dp0\.."
if "%~1"=="" (
    python version-tracker/tracker.py --config version-tracker/apps.json
) else (
    python version-tracker/tracker.py --config version-tracker/apps.json --html-source "%~1"
)
