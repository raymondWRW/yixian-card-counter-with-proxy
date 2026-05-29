# YiXian Counter (proxy-driven)

A small always-on-top window that reads YiXianPai's game traffic through a
local proxy and shows, live:

- **Card counter** — copies of each card remaining in your deck (8 per card;
  drawing removes 1, rerolling removes 2).
- **Board / hand / opponent** — exact current state from the network feed (no
  screen capture, no calibration).
- **Damage calculator** — first-8-turns damage via the `yi-sim` engine, in two
  modes: **solo** (your board vs a dummy) and **matchup** (your board vs the
  opponent's actual board this round). Toggle with the `matchup`/`solo` button.

It replaces the old image-detection app: the proxy decodes the game's WebSocket
frames directly, so detection is exact and the opponent's real board is known.

## Architecture

One Python process:

- mitmproxy (embedded `DumpMaster`, local/WinDivert mode) decodes traffic →
  `GameState` objects on a queue (`proxy/`),
- a consumer thread builds a JSON view-model (`proxy_view.py`) and pushes it to
  the UI,
- a frameless, always-on-top **pywebview** window renders it; the JS `yi-sim`
  damage engine runs inside the page (`web/yisim.bundle.js`).

```
game ⇄ WSS ⇄ mitmproxy(addon) → state_queue → consumer → view-model
                                                   │ window.evaluate_js
                                            pywebview window (WebView2)
                                            web/ui.js + yisim.bundle.js
```

## First-time setup

Requires Python 3.13 (a `.venv` is already created) and, for rebuilding the
damage bundle, Node.js.

```powershell
# Python deps (already installed in .venv)
.\.venv\Scripts\python.exe -m pip install pywebview mitmproxy blackboxprotobuf msgpack websockets

# Damage engine bundle (build-time only; output committed to web/yisim.bundle.js)
npm install
node build_yisim.mjs          # → web/yisim.bundle.js
.\.venv\Scripts\python.exe build_fate_map.py   # → proxy/fate_talent_map.json
```

### Proxy certificate (one-time, for live capture)

The game uses HTTPS/WSS, so mitmproxy's CA certificate must be trusted:

1. Run the app once (or `mitmdump`) to generate `%USERPROFILE%\.mitmproxy\`.
2. Install `mitmproxy-ca-cert.cer` into **Local Machine → Trusted Root
   Certification Authorities** (run as Administrator).

Local/WinDivert mode is used because the Unity client ignores the Windows proxy
setting — so **run the app as Administrator** for live capture.

## Running

```powershell
# Live capture (needs Administrator + cert installed). Then launch YiXianPai.
.\.venv\Scripts\python.exe app.py

# Replay a captured session into the UI (no admin) — great for testing:
$env:YX_REPLAY=1; .\.venv\Scripts\python.exe app.py
#   optionally set $env:YX_REPLAY_PATH to a traffic.jsonl

# Static demo (no proxy):
$env:YX_DEMO=1; .\.venv\Scripts\python.exe app.py
```

**Run the game in Borderless Windowed** (not exclusive fullscreen) so the
always-on-top window can draw over it. Drag the window by its title bar; the
`📌` button toggles always-on-top, `✕` quits.

## Offline tools

```powershell
# Print parsed GameState from a captured traffic.jsonl:
.\.venv\Scripts\python.exe runtime.py replay "path\to\traffic.jsonl" 50
```

## Verification

- **Replay** any captured `traffic.jsonl` and confirm board/hand/counter/damage
  track the session (`runtime.py replay`, or `YX_REPLAY=1`).
- **Damage parity:** for a fixed board the solo numbers should match the old
  Electron app's output before trusting matchup mode.
- **Live smoke test:** launch as admin, start YiXianPai (Borderless Windowed),
  play a round; the panel updates each round without stealing focus.

## Layout

```
app.py                  entry: window + worker threads
runtime.py              proxy embed, consumer, replay harness
proxy_view.py           GameState → view-model, Counter, fate mapping
proxy/                  ported decode/parse layer + addon (trimmed) + maps
web/                    index.html, ui.js, app.css, yisim.bundle.js
vendor/yisim/           yi-sim engine source + entry (bundled into web/)
build_yisim.mjs         esbuild bundler for the damage engine
build_fate_map.py       generates proxy/fate_talent_map.json
```
