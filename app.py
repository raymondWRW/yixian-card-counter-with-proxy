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
import sys
import threading
from pathlib import Path

import webview

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
INDEX_HTML = WEB_DIR / "index.html"
COUNTER_HTML = WEB_DIR / "counter.html"
REVIEW_HTML = WEB_DIR / "review.html"
DETAIL_HTML = WEB_DIR / "game_detail.html"

# Window handles, set in main(); used by the consumer thread to push state.
# _window      — main window (round bar / damage / boards / hand)
# _counter_win — companion window (deck counter only, lite-style)
# _review_win  — review window (game history, stats); opened on demand by the
#                main window's Review button
# _detail_win  — game-detail window: per-round boards / fates / winner
_window = None
_counter_win = None
_review_win = None
_detail_win = None
# Selected game_id for the detail window — JS reads this on load.
_detail_game_id = None

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
        # Quit all windows so the process exits when any window's ✕ is
        # clicked. pywebview keeps the event loop alive as long as ANY
        # window is open, so we must destroy them all.
        for win in (_counter_win, _review_win, _window):
            if win is not None:
                try: win.destroy()
                except Exception: pass

    # ── Review-window helpers (used by web/review.js + main-window button) ──
    def open_review(self):
        """Open the review window (lazy — creates it on first click).
        Called from web/ui.js when the user clicks the Review button."""
        global _review_win
        if _review_win is not None:
            try:
                _review_win.show()
                return True
            except Exception:
                _review_win = None
        try:
            _review_win = webview.create_window(
                "Review · 复盘",
                url=str(REVIEW_HTML),
                width=720, height=520, min_size=(420, 320),
                resizable=True, frameless=True, easy_drag=False,
                on_top=False,
                js_api=self,
            )
            return True
        except Exception as e:
            print(f"[review] open failed: {e}", flush=True)
            return False

    def close_review(self):
        """Hide the review window (from its own ✕ button)."""
        global _review_win
        if _review_win is not None:
            try: _review_win.destroy()
            except Exception: pass
            _review_win = None

    def move_review(self, x, y):
        """Move the review window — review.js calls this from a titlebar drag."""
        if _review_win is not None:
            try: _review_win.move(int(x), int(y))
            except Exception: pass

    def resize_review(self, w, h):
        """Resize the review window — review.js calls this when the user drags
        the bottom-right handle. Width and height come from the JS side scaled
        by the persisted reviewScale."""
        if _review_win is not None:
            try: _review_win.resize(int(w), int(h))
            except Exception: pass

    # ── Game-detail window (查看 button) ─────────────────────────────────────
    def open_game_detail(self, game_id: str):
        """Open the per-round detail window for a given game (lazy-create)."""
        global _detail_win, _detail_game_id
        _detail_game_id = game_id
        if _detail_win is not None:
            try:
                # Reload to pick up the new game_id, then bring to front.
                _detail_win.load_url(str(DETAIL_HTML))
                _detail_win.show()
                return True
            except Exception:
                _detail_win = None
        try:
            _detail_win = webview.create_window(
                "查看",
                url=str(DETAIL_HTML),
                width=900, height=640, min_size=(560, 380),
                resizable=True, frameless=True, easy_drag=False,
                on_top=False, js_api=self,
            )
            return True
        except Exception as e:
            print(f"[detail] open failed: {e}", flush=True)
            return False

    def close_detail(self):
        """Close the detail window (✕ button)."""
        global _detail_win
        if _detail_win is not None:
            try: _detail_win.destroy()
            except Exception: pass
            _detail_win = None

    def move_detail(self, x, y):
        if _detail_win is not None:
            try: _detail_win.move(int(x), int(y))
            except Exception: pass

    def resize_detail(self, w, h):
        if _detail_win is not None:
            try: _detail_win.resize(int(w), int(h))
            except Exception: pass

    def get_detail_game_id(self):
        """game_detail.js reads this on load to know which game to render."""
        return _detail_game_id

    def game_detail(self, game_id: str):
        """Return per-round detail (ME / OPP boards, fates, winner)."""
        try:
            sys.path.insert(0, str(BASE_DIR / "proxy"))
            import game_archive
            d = game_archive.game_detail(game_id)
            return d or {"error": "game not found", "rounds": []}
        except Exception as e:
            return {"error": str(e), "rounds": []}

    def list_games(self):
        """Return the list of recorded games for the review UI."""
        try:
            sys.path.insert(0, str(BASE_DIR / "proxy"))
            import game_archive
            return game_archive.list_games()
        except Exception as e:
            print(f"[review] list_games failed: {e}", flush=True)
            return []

    def review_game(self, game_id: str):
        """For each lost round in this folder-format game, run yisim against
        random permutations of the played board to find a winning arrangement.

        Pulls per-round state (ME + OPPONENT board, fates, hp/tipo/xiuwei) from
        the recorded deck_tracker.jsonl, builds a payload identical to the one
        yisim_review.js consumes, and reports which lost rounds were winnable.
        """
        try:
            sys.path.insert(0, str(BASE_DIR / "proxy"))
            import game_archive
            # Counter recordings have a battle_log/<id>/ folder; imported games
            # (from recentBattleDatas) don't — for those the payload is built
            # straight from the recent record instead.
            folder = BASE_DIR / "battle_log" / game_id
            is_folder = folder.is_dir()
            g = game_archive.load_game(game_id)
            if not g:
                return {"error": "load_game returned None",
                        "id": game_id, "winnable_rounds": [], "lost_rounds": []}
            lost = [r["round"] for r in g.get("rounds", [])
                    if not r.get("won", False) and r.get("round")]
            if not lost:
                return {"id": game_id, "lost_rounds": [],
                        "winnable_rounds": [], "details": []}

            import subprocess
            import json as _json
            review_js = str(BASE_DIR / "tools" / "yisim_review.js")
            winnable = []
            details = []
            for rn in lost:
                payload = (game_archive.build_review_payload(folder, rn)
                           if is_folder
                           else game_archive.build_recent_review_payload(game_id, rn))
                if not payload:
                    details.append({"round": rn,
                                    "skipped": "no per-round state recorded"})
                    continue
                try:
                    proc = subprocess.run(
                        ["node", review_js],
                        input=_json.dumps({"round": payload, "max_perms": 300}),
                        capture_output=True, text=True,
                        encoding="utf-8", timeout=60,
                    )
                    out = _json.loads(proc.stdout or "{}")
                except Exception as e:
                    details.append({"round": rn, "error": str(e)})
                    continue
                if out.get("win"):
                    winnable.append(rn)
                    details.append({
                        "round": rn, "win": True,
                        "tried": out.get("tried"),
                        "end_turn": out.get("end_turn"),
                        "winning_slots": out.get("winning_slots"),
                        "used_hand": out.get("used_hand"),
                    })
                else:
                    details.append({
                        "round": rn, "win": False,
                        "tried": out.get("tried"),
                        "closest_gap": out.get("closest_dmg_gap"),
                        "outcome": out.get("outcome"),
                    })
            return {
                "id": game_id,
                "lost_rounds": lost,
                "winnable_rounds": winnable,
                "details": details,
            }
        except Exception as e:
            import traceback
            print(f"[review] {traceback.format_exc()}", flush=True)
            return {"error": str(e), "winnable_rounds": [], "lost_rounds": []}

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
    # damageMode is locked to "solo" — matchup mode was removed from the UI.
    "damageMode": "solo",
    "rollMode": "average",     # "average" | "high" | "low"
    "onTop": True,
    # UI scale persisted per-window. The bottom-right drag handle in each
    # window writes back to these via set_setting; the JS reads them on
    # startup and applies CSS zoom so the layout stays proportional.
    "uiScale": 1.0,
    "counterScale": 1.0,
    "reviewScale": 1.0,
    "detailScale": 1.0,
    # Counter window: when True, collapse to show only the cards in hand.
    "counterHandOnly": False,
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

    YX_DEMO   — push one static demo view-model (no source connected).
    YX_REPLAY — play back a captured traffic.jsonl into the UI.
    YX_PROXY  — opt-in legacy: mitmproxy TLS MITM (needs admin + CA cert).
                Loads from proxy[outdated]/ — see its README. Useful when
                frida is blocked.
    default   — frida hook on the game's ProtobufParser (no cert, no admin).
                Set YX_GAME_EXE for a one-off path override, or YX_ATTACH=1
                to attach to an already-running game.
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

    # YX_PROXY=1 → legacy mitmproxy path. Loaded on demand from the outdated
    # folder so the default build doesn't ship mitmproxy at all.
    if os.environ.get("YX_PROXY"):
        # Add proxy[outdated]/ to sys.path so we can import the legacy bits.
        outdated_dir = BASE_DIR / "proxy[outdated]"
        if str(outdated_dir) not in sys.path:
            sys.path.insert(0, str(outdated_dir))
        try:
            import cert_setup
            status = cert_setup.ensure_cert_trusted(
                lambda *a: print(*a, flush=True))
            print(f"[cert] {status}", flush=True)
        except Exception as e:
            print(f"[cert] setup skipped: {e}", flush=True)
        from proxy_runtime import start_proxy as _legacy_start_proxy
        threading.Thread(target=_legacy_start_proxy,
                         daemon=True, name="proxy").start()
        threading.Thread(
            target=runtime.start_consumer, args=(push_state,),
            daemon=True, name="consumer",
        ).start()
        return

    # Default: frida hook on the game's ProtobufParser. No cert, no admin.
    attach = os.environ.get("YX_ATTACH", "0") != "0"
    game_exe = os.environ.get("YX_GAME_EXE")
    if not game_exe and not attach:
        # Fallback: the same config file the native HUD uses.
        cfg_path = BASE_DIR / "native_hud" / "bridge" / "YiXianHUD_config.json"
        if cfg_path.exists():
            try:
                game_exe = json.loads(cfg_path.read_text(encoding="utf-8")
                                      ).get("game_exe")
            except Exception:
                pass
    threading.Thread(
        target=runtime.start_frida_capture,
        kwargs={"game_exe": game_exe, "attach_mode": attach},
        daemon=True, name="frida-capture",
    ).start()
    threading.Thread(
        target=runtime.start_consumer, args=(push_state,),
        daemon=True, name="consumer",
    ).start()


def _patch_winforms_on_top():
    """Fix a pywebview freeze: its winforms ``set_on_top`` writes ``Form.TopMost``
    directly from the JS-API worker thread (``js_bridge_call`` runs every API call
    off the UI thread). Toggling TopMost off-thread makes WinForms recreate the
    window handle on the wrong thread, which breaks the message pump and FREEZES
    the window — exactly what clicking the 📌 pin did. Every other window op
    (move/resize/show) marshals onto the UI thread via ``Invoke``; ``set_on_top``
    is the one that forgot to. Patch it to do the same. No-op off Windows / if the
    backend isn't winforms."""
    if not sys.platform.startswith("win"):
        return
    try:
        from webview.platforms import winforms as wf
        from System import Func, Type

        def _set_on_top(uid, on_top):
            form = wf.BrowserView.instances.get(uid)
            if form is None:
                return
            def _apply():
                form.TopMost = on_top
            if form.InvokeRequired:
                form.Invoke(Func[Type](_apply))   # marshal to the UI thread
            else:
                _apply()

        wf.set_on_top = _set_on_top
    except Exception as e:
        print(f"[on_top patch skipped] {e}", flush=True)


def main():
    global _window, _counter_win
    _patch_winforms_on_top()
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
    # Open the WebView2 dev tools only when YX_DEVTOOLS is set — NOT on
    # YX_DEBUG (that one just enables battle_log storage), so the normal
    # debug/storage run doesn't pop dev tools every launch.
    webview.start(_start_workers, debug=bool(os.environ.get("YX_DEVTOOLS")))


if __name__ == "__main__":
    main()
