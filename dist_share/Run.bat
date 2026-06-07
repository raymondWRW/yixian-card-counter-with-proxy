@echo off
REM Self-elevating launcher for YiXian Counter.
REM Right-clicking the .exe and choosing "Run as administrator" works too;
REM this just makes double-click work.

fltmc >nul 2>&1
if %errorlevel% NEQ 0 (
    powershell -Command "Start-Process -FilePath '%~dp0YiXianCounter.exe' -Verb RunAs"
    exit /b
)

start "" "%~dp0YiXianCounter.exe"
