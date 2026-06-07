@echo off
setlocal EnableDelayedExpansion
title YiXian Counter - Setup

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
echo   YiXian Counter - First-time Setup
echo ============================================================
echo.

REM --- Step 0: WebView2 Runtime check --------------------------------------
echo [0/3] Checking for Microsoft Edge WebView2 Runtime...
set "WV2_GUID={F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
powershell -NoProfile -Command "$keys = @('HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\%WV2_GUID%', 'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\%WV2_GUID%', 'HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\%WV2_GUID%'); $found = $false; foreach ($k in $keys) { if (Test-Path $k) { $v = (Get-ItemProperty -Path $k -Name pv -ErrorAction SilentlyContinue).pv; if ($v -and $v -ne '0.0.0.0') { Write-Host \"      OK - WebView2 version $v found.\"; $found = $true; break } } }; if (-not $found) { exit 1 }"
if %errorlevel% NEQ 0 (
    echo.
    echo ============================================================
    echo   ERROR: Microsoft Edge WebView2 Runtime not installed.
    echo ============================================================
    echo.
    echo   The counter windows need WebView2 to render. Without it
    echo   the windows open blank.
    echo.
    echo   1. Download the small ^(~2 MB^) installer from:
    echo      https://developer.microsoft.com/microsoft-edge/webview2/
    echo      ^(click "Download" under "Evergreen Bootstrapper"^)
    echo.
    echo   2. Run the installer ^(takes ~30 seconds, no reboot needed^).
    echo.
    echo   3. Re-run this Setup.bat afterwards.
    echo.
    echo   Windows 11 has WebView2 pre-installed; this is typically only
    echo   needed on Windows 10.
    echo.
    pause
    exit /b 1
)
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
start "" "%~dp0YiXianCounter.exe"

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
taskkill /F /IM YiXianCounter.exe >nul 2>&1
echo.

:installcert
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
echo   Double-click Run.bat to launch YiXian Counter.
echo ============================================================
echo.
pause
