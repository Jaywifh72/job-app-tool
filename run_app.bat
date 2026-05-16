@echo off
cd /d "C:\dev\job-app-tool"
echo Starting Job App Tool...
echo.
start "Job App Tool" cmd /k "python app.py"
timeout /t 3 /nobreak >nul
start http://127.0.0.1:5000
echo Browser opened. Close this window to keep the server running.
pause
