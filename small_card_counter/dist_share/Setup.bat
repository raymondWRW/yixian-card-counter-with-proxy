@echo off
setlocal EnableDelayedExpansion
title YiXian Counter (Lite) - Setup

REM --- Self-elevate ---------------------------------------------------------
fltmc >nul 2>&1
if %errorlevel% NEQ 0 (
    echo Requesting administrator rights...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo.
echo ============================================================
echo   YiXian Counter (Lite) - First-time Setup
echo ============================================================
echo.

REM --- Step 1: Defender exclusion ------------------------------------------
echo [1/3] Adding Windows Defender exclusion for this folder...
powershell -NoProfile -Command "try { Add-MpPreference -ExclusionPath '%~dp0' -ErrorAction Stop; Write-Host '      OK - exclusion added.' } catch { Write-Host ('      Skipped - ' + $_.Exception.Message) }"
echo.

REM --- Step 2: Generate mitmproxy CA cert via short app launch -------------
set "CERT=%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.cer"

if exist "%CERT%" (
    echo [2/3] mitmproxy CA cert already exists - skipping generation.
    goto installcert
)

echo [2/3] Launching app briefly to generate the mitmproxy CA cert...
start "" "%~dp0YiXianCounterLite.exe"

set /a tries=0
:waitcert
if exist "%CERT%" goto gotcert
set /a tries+=1
if !tries! GEQ 60 goto certtimeout
timeout /t 1 /nobreak >nul
goto waitcert

:gotcert
echo       OK - cert generated.
goto killapp

:certtimeout
echo       Timed out waiting for the cert file.
echo       App may not have started. Check Windows Defender / SmartScreen.

:killapp
taskkill /F /IM YiXianCounterLite.exe >nul 2>&1
echo.

:installcert
REM --- Step 3: Install the cert into Trusted Root --------------------------
if not exist "%CERT%" (
    echo [3/3] FAILED - no cert to install. Aborting.
    echo       Try running Setup.bat again, or check the README.
    echo.
    pause
    exit /b 1
)

echo [3/3] Installing mitmproxy CA cert into Trusted Root...
certutil -addstore -f Root "%CERT%" >nul 2>&1
if %errorlevel% EQU 0 (
    echo       OK - cert installed.
) else (
    echo       certutil reported a non-zero exit. Cert may already be trusted.
)
echo.

echo ============================================================
echo   Setup complete!
echo   Double-click Run.bat to launch the counter.
echo ============================================================
echo.
pause
