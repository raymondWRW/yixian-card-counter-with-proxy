YiXian Counter (Main)
=====================
(Chinese: see 说明.txt)

Two always-on-top overlay windows for YiXianPai:
  - Main window  — round / damage simulator (real-matchup or solo)
  - Counter      — cards left in your deck

Both windows are draggable by the title bar and auto-resize to fit. Drag
the bottom-right corner of either window to scale up/down proportionally.


FIRST-TIME SETUP  (do this once)
--------------------------------
1. Extract this folder anywhere (Desktop is fine).
2. Double-click  Setup.bat
3. Click YES on the User Account Control (UAC) prompt.
4. Wait until you see "Setup complete!" and press a key to close the window.

If SmartScreen blocks the .exe ("Windows protected your PC"):
  - Click "More info"  ->  "Run anyway".


DAILY USE
---------
1. Double-click  Run.bat
2. Click YES on the UAC prompt.
3. Start YiXianPai. Both windows populate within a few seconds.

The .exe must run with administrator rights because the proxy
intercepts traffic at the kernel level (WinDivert driver).


GAME LOGS (for debugging + future review feature)
-------------------------------------------------
The app writes a folder per game under  battle_log\<YYYY-MM-DD_HHMMSS>\
containing:
  msgdump.jsonl       — every WebSocket frame, decoded
  shadow_log.txt      — human-readable game-state log
  deck_tracker.jsonl  — what the UI saw, per frame
  battle_log.json     — copy of the game's own BattleLog.json (HP per round)

If something looks wrong, zip the most-recent folder under  battle_log\
and send it back.

Logs are written next to the .exe. If you want to clear them, just
delete the  battle_log\  folder.


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


PRIVACY NOTE  (read this)
-------------------------
Setup.bat installs a mitmproxy Certificate Authority (CA) into your
Windows Trusted Root store. This is required so the proxy can decrypt
the game's HTTPS WebSocket traffic.

While the proxy is running, anything that holds this CA's private key
could intercept your other HTTPS traffic. The private key lives in
your own  %USERPROFILE%\.mitmproxy\  folder and is generated locally
on your machine - it is NOT shared with the sender of this .exe.

Only install software like this from people you trust.


UNINSTALL
---------
1. Remove the trusted CA:
   certutil -delstore Root mitmproxy
2. Remove the Defender exclusion (PowerShell as admin):
   Remove-MpPreference -ExclusionPath "<path to this folder>"
3. Delete this folder.
4. Optionally delete  %USERPROFILE%\.mitmproxy\  to remove the
   generated cert files.


TROUBLESHOOTING
---------------
- Windows open but counters never update:
    The proxy isn't intercepting. Most common causes:
      a) You launched the .exe without admin rights - use Run.bat.
      b) Cert isn't trusted - re-run Setup.bat.
      c) Antivirus blocked WinDivert - add an exclusion or temporarily
         disable real-time protection.

- "Windows cannot access the specified device" on launch:
    Defender deleted the .exe. Restore it from the quarantine and
    re-run Setup.bat (the Defender exclusion step prevents recurrence).

- Game won't load matches at all after install:
    Cert trust may be misconfigured. Re-run Setup.bat. If still broken,
    uninstall (see above) and try again.

- Damage panel shows "未识别卡片 (灵羽)":
    A 灵羽 (Spirit Feather) on your board didn't find a valid lv1
    merge target (qi/agility card). The damage sim can't predict the
    real merged value, so it bails rather than guess. Place a lv1
    qi/agility card on the board and the sim will re-engage.
