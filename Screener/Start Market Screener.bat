@echo off
title US Market Screener
cd /d "%~dp0"
echo Starting US Market Screener...
where python >nul 2>nul
if %errorlevel%==0 (
    python launch.py
) else (
    py -3 launch.py
)
echo.
echo The screener has stopped. Press any key to close this window.
pause >nul
