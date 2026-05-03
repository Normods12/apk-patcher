@echo off
setlocal
cd /d "%~dp0"
echo Starting Premium APK Automation Dashboard...
echo Open http://localhost:8000 in your browser.
python dashboard_v2.py
pause
