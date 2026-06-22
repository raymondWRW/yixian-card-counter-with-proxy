# run_live.ps1 — launch the live proxy + UI as Administrator.
# Local/WinDivert mode needs elevation; this self-elevates if needed.
#
#   .\run_live.ps1            normal live run
#   .\run_live.ps1 -Capture   also record diagnostic traffic to
#                             proxy\output\traffic.jsonl + unhandled_types.txt

param([switch]$Capture)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "Re-launching as Administrator..."
    $argList = @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    if ($Capture) { $argList += '-Capture' }
    Start-Process powershell -Verb RunAs -ArgumentList $argList
    return
}

Set-Location $here
$env:PYTHONUTF8 = '1'
if ($Capture) {
    $env:YX_CAPTURE = '1'
    # R24-Phase-A: pair with a one-shot first-GameStatus structural dump so
    # we can audit every per-player protobuf field (HP, fates, etc.).
    $env:YX_DUMP_GS = '1'
    # Debug mode: per-game folders under battle_log\<timestamp>\ containing
    # msgdump.jsonl, shadow_log.txt, deck_tracker.jsonl, battle_log.json.
    $env:YX_DEBUG = '1'
    Write-Host "DIAGNOSTIC CAPTURE ON -> proxy\output\traffic.jsonl (fresh each run)."
    Write-Host "GS FIELD DUMP ON      -> proxy\output\gs_field_dump.txt (first frame only)."
    Write-Host "DEBUG MODE ON         -> battle_log\<timestamp>\ per-game folders."
} else {
    Remove-Item Env:\YX_CAPTURE -ErrorAction SilentlyContinue
    Remove-Item Env:\YX_DUMP_GS -ErrorAction SilentlyContinue
    Remove-Item Env:\YX_DEBUG -ErrorAction SilentlyContinue
}
Write-Host "Starting YiXian Counter (live). Launch YiXianPai in Borderless Windowed."
& "$here\.venv\Scripts\python.exe" "$here\app.py"
