YiXian Counter (Main)
=====================
(Chinese: see 说明.txt)

Two always-on-top overlay windows for YiXianPai:
  - Main window  — round / damage simulator (real-matchup or solo)
  - Counter      — cards left in your deck

Both windows are draggable by the title bar and auto-resize to fit. Drag
the bottom-right corner of either window to scale up/down proportionally.


HOW TO USE
----------
1. Extract this folder anywhere (Desktop is fine).
2. Double-click  YiXianCounter.exe
   (If SmartScreen shows "Windows protected your PC":
    click "More info" -> "Run anyway".)
3. Start YiXianPai. Both windows populate within a few seconds.

That's it — no setup step, no administrator rights, no certificate.

The counter reads the game directly (it hooks the game's own data, no
network proxy). On the FIRST run it also downloads a small engine
component (~42 MB) used by the damage / 复盘 features; this needs an
internet connection but only happens once. The card counter itself works
without it.


IF SOMETHING GOES WRONG
-----------------------
The app tells you what's wrong on screen:

  - A popup "Missing runtime" at launch:
      Microsoft Edge WebView2 Runtime isn't installed (needed to draw the
      windows). It's pre-installed on Windows 11; on Windows 10 download
      the free installer from:
        https://developer.microsoft.com/microsoft-edge/webview2/
      Run it (~30s, no reboot), then start YiXianCounter.exe again.

  - Red banner "Game not found":
      YiXianPai isn't running and wasn't found at the default Steam path
      (C:\Program Files (x86)\Steam\steamapps\common\YiXianPai\).
      Just start the game — the counter will pick it up. If your game is
      installed elsewhere, set the YX_GAME_EXE environment variable to the
      full path of YiXianPai.exe.

  - Red banner "Can't hook game":
      Your antivirus / Windows Defender blocked the app from reading the
      game. Add this folder to your antivirus exclusions, then relaunch.

  - Amber banner "Engine download failed":
      No internet, or gitee.com is unreachable. The card counter still
      works; the damage / 复盘 features need this one-time download. Retry
      once you're online.

  - Blue banner "Connecting to game…":
      Normal — it clears automatically once you start a match.

  - Damage panel shows "未识别卡片 (灵羽)":
      A 灵羽 (Spirit Feather) on your board has no valid lv1 merge target
      (qi/agility card). Place a lv1 qi/agility card and the sim re-engages.


GAME LOGS (for debugging + the review feature)
----------------------------------------------
The app writes a folder per game under  battle_log\<YYYY-MM-DD_HHMMSS>\
containing:
  msgdump.jsonl       — every WebSocket frame, decoded
  shadow_log.txt      — human-readable game-state log
  deck_tracker.jsonl  — what the UI saw, per frame
  battle_log.json     — copy of the game's own BattleLog.json (HP per round)

If something looks wrong, zip the most-recent folder under  battle_log\
and send it back. Logs are written next to the .exe; delete the
battle_log\  folder to clear them.

Diagnostic logs (startup errors, engine sync) are also written to:
  %LOCALAPPDATA%\YiXianCounter\app.log
  %LOCALAPPDATA%\YiXianCounter\oracle-sync.log


AUTO-UPDATE
-----------
On launch the app checks Gitee for a newer version. If one is found, a
small "有新版本" banner appears in the main window — click "更新" to
download, verify (SHA256), and self-install. No GitHub / no proxy
needed; the check uses gitee.com which works from mainland China.

Updates are prompted only — never silent. Dismiss with the X to defer.


SYSTEM REQUIREMENTS
-------------------
- Windows 10 or 11, 64-bit.
- Microsoft Edge WebView2 Runtime (pre-installed on Win11; free download:
  https://developer.microsoft.com/microsoft-edge/webview2/ )
- An internet connection on first launch (for the one-time engine download).


UNINSTALL
---------
Just delete this folder. To also remove the cached engine and logs:
  delete  %LOCALAPPDATA%\YiXianCounter\
