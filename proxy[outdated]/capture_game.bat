@echo off
REM ============================================================================
REM  capture_game.bat  —  DEBUG capture launcher (double-click this).
REM
REM  Runs the YiXian Counter as Administrator WITH diagnostic capture ON
REM  (YX_CAPTURE=1). No flags to remember. An elevated console window opens;
REM  watch it for:
REM        [capture] ON -> ...\proxy\output\traffic.jsonl
REM        [capture] N frames recorded     (once you're in a game)
REM  If you instead see "[capture] OFF", something went wrong — tell Claude.
REM
REM  Play one short game reproducing the bug, then close the app window.
REM  The raw frames land in proxy\output\traffic.jsonl (reset fresh each run).
REM ============================================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_live.ps1" -Capture
echo.
echo This launcher window can be closed; the game capture runs in the elevated window.
pause
