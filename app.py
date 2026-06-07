"""
app.py
──────
Entry point for the proxy-driven YiXianPai card counter + damage calculator.

A single Python process that:
  1. (M2) starts mitmproxy's DumpMaster on a background thread to decode the
     game's WebSocket traffic into GameState objects (pushed onto state_queue),
  2. (M3) drains state_queue on a consumer thread, builds a JSON view-model,
     and pushes it to the UI via window.evaluate_js,
  3. opens a frameless, always-on-top pywebview window that renders the
     counter / board / damage (the damage sim — yisim — runs as JS in the page).

Run:  .venv/Scripts/python.exe app.py
"""
import json
import os
import threading
from pathlib import Path

import webview

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
INDEX_HTML = WEB_DIR / "index.html"
COUNTER_HTML = WEB_DIR / "counter.html"

# Window handles, set in main(); used by the consumer thread to push state.
# _window      — main window (round bar / damage / boards / hand)
# _counter_win — companion window (deck counter only, lite-style)
_window = None
_counter_win = None

# Height of the titlebar in px (must match #titlebar height in app.css). When the
# user minimizes the window, we resize to this height to leave only the titlebar
# visible; on restore we go back to _saved_size.
TITLEBAR_HEIGHT = 34
_saved_size = None  # (width, height) before minimizing


class Api:
    """Methods callable from JS via window.pywebview.api.*.

    Kept tiny on purpose: the heavy data flow is Python → JS (push); this is
    only for UI-initiated actions (toggle damage mode, pin/unpin, quit).
    """

    def __init__(self):
        self.settings = _load_settings()

    def get_settings(self):
        return self.settings

    def get_version(self):
        """Return the bundled VERSION string. JS shows it in the titlebar."""
        try:
            from version import VERSION
            return VERSION
        except Exception:
            return "?"

    def start_update(self):
        """Download + verify + apply the pending update. Triggered when the
        user clicks the "更新" button on the update banner. Process exits
        immediately so updater.bat can swap the file lock."""
        try:
            import updater
            manifest = getattr(self, "_pending_update", None)
            if not manifest:
                manifest = updater.check_for_update()
            if not manifest:
                return {"ok": False, "error": "no update available"}
            new_exe = updater.download_update(manifest)
            updater.apply_update(new_exe)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        import threading
        import time
        def _quit():
            time.sleep(0.4)
            try:
                if _counter_win is not None:
                    _counter_win.destroy()
            except Exception:
                pass
            try:
                if _window is not None:
                    _window.destroy()
            except Exception:
                pass
            os._exit(0)
        threading.Thread(target=_quit, daemon=True).start()
        return {"ok": True}

    def set_setting(self, key, value):
        self.settings[key] = value
        _save_settings(self.settings)
        return self.settings

    def set_on_top(self, on_top):
        if _window is not None:
            _window.on_top = bool(on_top)
        return bool(on_top)

    def move(self, x, y):
        """Move the window's top-left to (x, y) in screen pixels.

        Called from the JS title-bar drag handler. WebView2 doesn't honor
        the -webkit-app-region CSS, so dragging is implemented manually.
        """
        if _window is not None:
            try:
                _window.move(int(x), int(y))
            except Exception:
                pass

    def set_collapsed(self, collapsed):
        """Shrink the window to titlebar height (collapsed=True) or restore
        the previous size. The CSS handles hiding the body content; we just
        resize the OS window so it doesn't leave empty space behind.
        """
        global _saved_size
        if _window is None:
            return
        try:
            if collapsed:
                _saved_size = (int(_window.width), int(_window.height))
                _window.resize(_saved_size[0], TITLEBAR_HEIGHT)
            else:
                w, h = _saved_size or (360, 720)
                _window.resize(int(w), int(h))
                _saved_size = None
        except Exception:
            pass
        return bool(collapsed)

    def quit(self):
        # Quit both windows so the process exits when either window's ✕ is
        # clicked. pywebview keeps the event loop alive as long as ANY
        # window is open, so we must destroy them both.
        if _counter_win is not None:
            try: _counter_win.destroy()
            except Exception: pass
        if _window is not None:
            try: _window.destroy()
            except Exception: pass

    # ── Counter-window helpers (used by web/counter.js) ─────────────────────
    def move_counter(self, x, y):
        """Move the counter window's top-left to (x, y) in screen pixels."""
        if _counter_win is not None:
            try: _counter_win.move(int(x), int(y))
            except Exception: pass

    def resize_counter(self, w, h):
        """Resize the counter window — counter.js calls this each render so
        the window auto-fits its content height."""
        if _counter_win is not None:
            try: _counter_win.resize(int(w), int(h))
            except Exception: pass

    def resize_main(self, w, h):
        """Resize the main window — ui.js calls this each render so the main
        window auto-fits its content height (same behavior as the lite /
        counter window). Width stays at whatever JS passes (currently fixed
        in ui.js); height tracks document.body.scrollHeight."""
        if _window is not None:
            try: _window.resize(int(w), int(h))
            except Exception: pass


# ─── Settings persistence (AppData) ───────────────────────────────────────────
def _settings_path() -> Path:
    base = os.environ.get("APPDATA") or str(BASE_DIR)
    d = Path(base) / "yixian-proxy-counter"
    d.mkdir(parents=True, exist_ok=True)
    return d / "settings.json"


_DEFAULT_SETTINGS = {
    "damageMode": "matchup",   # "matchup" | "solo"
    "rollMode": "average",     # "average" | "high" | "low"
    "onTop": True,
    # UI scale persisted per-window. The bottom-right drag handle in each
    # window writes back to these via set_setting; the JS reads them on
    # startup and applies CSS zoom so the layout stays proportional.
    "uiScale": 1.0,
    "counterScale": 1.0,
}


def _load_settings() -> dict:
    p = _settings_path()
    if p.exists():
        try:
            return {**_DEFAULT_SETTINGS, **json.loads(p.read_text(encoding="utf-8"))}
        except Exception:
            pass
    return dict(_DEFAULT_SETTINGS)


def _save_settings(settings: dict):
    try:
        _settings_path().write_text(
            json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


# ─── Pushing state to the UI ──────────────────────────────────────────────────
def push_state(view_model: dict):
    """Push a view-model dict to BOTH the main window and the counter window.

    Each window's `window.onState` picks the slices it cares about (the main
    window uses the full view-model; the counter window only reads
    `vm.counter.remaining` and `vm.round`).
    """
    payload = json.dumps(view_model, ensure_ascii=False)
    js = f"window.onState && window.onState({payload})"
    for w in (_window, _counter_win):
        if w is None:
            continue
        try:
            w.evaluate_js(js)
        except Exception:
            pass


# ─── Background workers (wired up in M2/M3) ───────────────────────────────────
def _push_demo_state():
    """M1 visual check: push a fake view-model so the window isn't blank."""
    import time
    time.sleep(1.0)
    push_state({
        "round": 5, "phase": "prep (demo)",
        "me": {
            "destiny": 100, "hp": 75, "xiuwei": 12, "tipo": 3,
            "realm_tier": 2, "unlocked": 7,
            "hand": [
                {"name": "劈山掌", "level": 2}, {"name": "云剑·探云", "level": 1},
                {"name": "研墨", "level": 2}, {"name": "轻剑", "level": 1},
            ],
            "board": [
                {"name": "劈山掌", "level": 2}, None, {"name": "研墨", "level": 1},
                {"name": "云剑·探云", "level": 1}, None, None, None, None,
            ],
        },
        "opponent": {
            "character": "Blue Phoenix", "destiny": 95, "hp": 80, "unlocked": 7,
            "board": [{"name": "烈焰", "level": 3}, {"name": "护盾", "level": 2}, None, None,
                      None, None, None, None],
        },
        "counter": {"remaining": {"云剑·闪风": 1, "云剑·飞刺": 3, "劈山掌": 2, "研墨": 4}},
        "damage": {"first8Turns": 184, "cumulativeDamage": [12, 31, 58, 84, 110, 139, 165, 184]},
    })


def _push_update_notice(manifest: dict):
    """Notify the main window's JS that an update is available. Called from
    the updater's background thread."""
    if _window is None:
        return
    payload = json.dumps({
        "version": manifest.get("version", ""),
        "notes": manifest.get("notes", ""),
    }, ensure_ascii=False)
    js = f"window.onUpdateAvailable && window.onUpdateAvailable({payload})"
    try:
        _window.evaluate_js(js)
    except Exception:
        pass
    api = getattr(_window, "_js_api_instance", None)
    if api is not None:
        api._pending_update = manifest


def _start_workers():
    """Start the data source feeding the UI.

    YX_DEMO   — push one static demo view-model (no proxy).
    YX_REPLAY — play back a captured traffic.jsonl into the UI (no admin).
    default   — live mitmproxy capture + consumer (needs admin / WinDivert).
    """
    # Auto-update: fire-and-forget Gitee check on startup. Short timeout +
    # daemon thread so an offline / slow network never delays the window.
    try:
        import updater
        updater.check_for_update_async(_push_update_notice)
    except Exception:
        pass

    if os.environ.get("YX_DEMO"):
        threading.Thread(target=_push_demo_state, daemon=True).start()
        return

    import runtime

    if os.environ.get("YX_REPLAY"):
        path = os.environ.get("YX_REPLAY_PATH") or None
        threading.Thread(
            target=runtime.start_replay_ui, args=(push_state,),
            kwargs={"path": path}, daemon=True, name="replay-ui",
        ).start()
        return

    threading.Thread(target=runtime.start_proxy, daemon=True, name="proxy").start()
    threading.Thread(
        target=runtime.start_consumer, args=(push_state,), daemon=True, name="consumer"
    ).start()


def main():
    global _window, _counter_win
    api = Api()
    # Main window — round bar + damage card only. (YOU / OPPONENT / HAND
    # sections moved to the counter window, so this can start short and
    # auto-resize from there.)
    _window = webview.create_window(
        title="YiXian Counter",
        url=INDEX_HTML.as_uri(),
        js_api=api,
        width=360,
        height=200,
        x=40, y=40,
        frameless=True,
        easy_drag=False,        # we drag via a dedicated header (-webkit-app-region)
        on_top=api.settings.get("onTop", True),
        background_color="#11141a",
        # R23: min-height lowered to TITLEBAR_HEIGHT so the minimize button
        # can actually shrink the window to a titlebar-only strip. The old
        # (300, 400) min was clamping `_window.resize(width, 34)` and leaving
        # a ~366px black widget below the titlebar. Frameless=True means
        # the user can't drag-resize edges, so a small min is safe.
        # min_size width lowered (300 → 200) so MIN_SCALE=0.6 in the JS
        # resize handle doesn't clamp the window at the bottom of its range.
        min_size=(200, TITLEBAR_HEIGHT),
    )
    # Stash the Api on the window so _push_update_notice can write the
    # pending manifest back into it (avoids a re-fetch when the user clicks
    # "更新" on the banner).
    _window._js_api_instance = api
    # Counter window — same JS API instance (shared settings, shared quit).
    # Lite-style: small, frameless, always-on-top. Auto-resizes height to
    # fit the counter list via Api.resize_counter() called from counter.js.
    _counter_win = webview.create_window(
        title="YiXian Counter — Cards Left",
        url=COUNTER_HTML.as_uri(),
        js_api=api,
        width=260,
        height=100,          # short start; counter.js auto-resizes to content
        x=420, y=40,         # placed to the right of the main window
        frameless=True,
        easy_drag=False,
        on_top=api.settings.get("onTop", True),
        background_color="#11141a",
        # Lowered to match the lite window's MIN_SCALE=0.6: 260 * 0.6 = 156.
        min_size=(150, 30),
    )
    webview.start(_start_workers, debug=bool(os.environ.get("YX_DEBUG")))


if __name__ == "__main__":
    main()
