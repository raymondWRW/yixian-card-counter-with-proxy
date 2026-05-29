YiXian Counter (Lite)
=====================
(Chinese: see 说明.txt)

A small overlay that shows the cards remaining in your YiXianPai deck.
Always-on-top, draggable by the title bar, auto-resizes to fit.


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
3. Start YiXianPai. The counter populates within a few seconds.

The .exe must run with administrator rights because the proxy
intercepts traffic at the kernel level (WinDivert driver).


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
- Window opens but counter never updates:
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
