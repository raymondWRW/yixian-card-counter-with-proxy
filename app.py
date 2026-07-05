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

# Bump when the review search logic changes (empty-slot candidates, go-first, …) so old
# cached solutions are recomputed. Combined with the game version, this keys the cache.
# v5: drop variants are 普攻-padded to the recorded slot count (unpadded 7-card lists
#     ran as 7-slot cycles and reported phantom wins); death round now included.
REVIEW_ANALYSIS_VERSION = 5


def _review_cache_file() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(BASE_DIR))) / "YiXianCounter" / "review_cache.json"


def _engine_stamp() -> str:
    """Game+engine version stamp. Changes when the game patches (the Oracle re-syncs and
    rewrites ORACLE_HOME/.oracle_version), so cached solutions for the OLD card rules are
    invalidated and re-analysed under the new ones."""
    try:
        home = os.environ.get("ORACLE_HOME")
        if home:
            m = Path(home) / ".oracle_version"
            if m.exists():
                return m.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return "nover"


def _review_cache_load() -> dict:
    try:
        return json.loads(_review_cache_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _review_cache_save(cache: dict):
    try:
        p = _review_cache_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
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
# Counter-only mode: hide the damage-calculator (main) window and run just the
# card counter + review. Auto-on in the packaged exe (the live calculator needs
# the Yi Xian Oracle engine, which the distributed build doesn't bundle). Dev
# runs show both windows; force either way with YX_COUNTER_ONLY=1 / =0.
# YX_BESTLINE=1 enables the live best-line panel, which lives in the MAIN window —
# so it un-hides the main window even in a frozen (normally counter-only) build.
# An explicit YX_COUNTER_ONLY=1 still wins.
_counter_only = (os.environ.get("YX_COUNTER_ONLY") == "1"
                 or (getattr(sys, "frozen", False)
                     and os.environ.get("YX_COUNTER_ONLY") != "0"
                     and os.environ.get("YX_BESTLINE") != "1"))
# Selected game_id for the detail window — JS reads this on load.
_detail_game_id = None
# Set True on the first view-model push so push_state can clear the
# "connecting…" diagnostic banner once live game data actually flows.
_live_connected = False

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
                import runtime
                runtime.stop_frida_capture()   # os._exit skips atexit — unhook first
            except Exception:
                pass
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
        # window is open, so we must destroy them all. Unhook the game FIRST —
        # leaving frida hooks in a game that outlives us causes game-side lag.
        try:
            import runtime
            runtime.stop_frida_capture()
        except Exception:
            pass
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
                # Reload the games list every time it's reopened (new games since last time).
                try: _review_win.evaluate_js("window.reloadGames && window.reloadGames()")
                except Exception: pass
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
        """For each lost round, replay the recorded matchup through the Yi Xian
        Oracle (the game's own combat code) over board permutations to find a
        winning arrangement. Oracle-only — the engine is always current with the
        installed game (oracle_bootstrap keeps it synced), so there's no yisim
        fallback. Imported (recentBattleDatas) games carry the bit-exact record
        the Oracle needs; counter-only folder games without a record are skipped.
        """
        try:
            sys.path.insert(0, str(BASE_DIR / "proxy"))
            import game_archive
            import oracle_sim
            import recent_battles
            g = game_archive.load_game(game_id)
            if not g:
                return {"error": "load_game returned None",
                        "id": game_id, "winnable_rounds": [], "lost_rounds": []}
            lost = [r["round"] for r in g.get("rounds", [])
                    if not r.get("won", False) and r.get("round")]
            if not lost:
                return {"id": game_id, "lost_rounds": [],
                        "winnable_rounds": [], "details": []}
            # Cache: a fully-analysed game is stored (keyed by game + engine + analysis version),
            # so re-opening 复盘 returns instantly instead of re-running the Oracle search. Patches
            # to the game OR the search logic change the stamp and trigger a fresh analysis.
            stamp = f"{_engine_stamp()}|{REVIEW_ANALYSIS_VERSION}"
            cache = _review_cache_load()
            hit = cache.get(game_id)
            if hit and hit.get("stamp") == stamp and hit.get("result"):
                r = dict(hit["result"]); r["cached"] = True
                return r
            if not oracle_sim.available():
                return {"id": game_id, "lost_rounds": lost, "winnable_rounds": [],
                        "details": [{"round": rn, "skipped": "engine preparing — try again shortly"}
                                    for rn in lost],
                        "error": "oracle not ready"}

            winnable = []
            details = []
            for rn in lost:
                out = None
                try:
                    me_side, b64 = recent_battles.round_stat_b64(game_id, rn)
                    if b64:
                        out = oracle_sim.whatif_from_stat(b64, me_side, deck_slots=8)
                except Exception as e:
                    print(f"[review] oracle round {rn} failed: {e}", flush=True)
                    out = None
                if out is None:
                    details.append({"round": rn,
                                    "skipped": "no in-game record for this round"})
                    continue
                if out.get("win"):
                    winnable.append(rn)
                    details.append({
                        "round": rn, "win": True, "engine": "oracle",
                        "tried": out.get("tried"),
                        "end_turn": out.get("end_turn"),
                        "winning_slots": out.get("winning_slots"),
                        "used_hand": out.get("used_hand"),
                        # Go-first line: this board only wins if the player takes the first turn
                        # (achievable by absorbing cards for cultivation; hand_cards = cards available).
                        "requires_go_first": out.get("requires_go_first"),
                        "hand_cards": out.get("hand_cards"),
                    })
                elif out.get("already_won"):
                    # The real engine says this matchup was actually won/drawn (the displayed
                    # "lost" flag comes from a coarser life-drop heuristic). Not a loss to fix.
                    details.append({
                        "round": rn, "win": False, "already_won": True, "engine": "oracle",
                        "original_life": out.get("original_life"),
                    })
                else:
                    details.append({
                        "round": rn, "win": False, "engine": "oracle",
                        "tried": out.get("tried"),
                        "closest_gap": out.get("closest_hpDelta"),
                        "closest_life": out.get("closest_life"),
                    })
            result = {
                "id": game_id,
                "lost_rounds": lost,
                "winnable_rounds": winnable,
                "details": details,
            }
            # Only cache a COMPLETE analysis (no per-round "skipped: engine preparing").
            if not any(d.get("skipped", "").startswith("engine") for d in details):
                cache[game_id] = {"stamp": stamp, "result": result}
                _review_cache_save(cache)
            return result
        except Exception as e:
            import traceback
            print(f"[review] {traceback.format_exc()}", flush=True)
            return {"error": str(e), "winnable_rounds": [], "lost_rounds": []}

    def oracle_matchup(self, me: dict, opp: dict, marginal: bool = True, rnd: int = 8):
        """Live matchup of MY board vs the OPPONENT's board via the Yi Xian Oracle
        (the game's own combat engine). Each side dict carries:
          {usedCards:[card ids], characterId, level(realm 1..5), extraMaxHp,
           talents:[ids], fateStrategies:[ids], sect, career, life, unlockGrids}
        `rnd` is the current round (destiny/命 damage scales with it).
        Returns {win, hpDelta, turns, lifeDamage, marginal:{slot: hp}} or {error}.

        Talents + fateStrategies (the 天衍 derivations the game derived) are
        captured from the wire on each side, so the real engine applies every
        derivation/fate/talent effect during combat — no card-implementation lag.
        """
        try:
            sys.path.insert(0, str(BASE_DIR / "proxy"))
            import oracle_sim
            if not oracle_sim.available():
                return {"error": "oracle not available"}
            r = oracle_sim.matchup(me or {}, opp or {}, marginal=bool(marginal),
                                   rnd=int(rnd) if rnd else 8)
            return r or {"error": "matchup returned None"}
        except Exception as e:
            import traceback
            print(f"[oracle] {traceback.format_exc()}", flush=True)
            return {"error": str(e)}

    def get_pending_status(self):
        """Return the diagnostic notices active right now. counter.js calls this
        once on load so a problem raised BEFORE the page finished loading (e.g.
        'game not found' fired during startup) still appears, instead of being
        lost to the push/load race."""
        return list(_status_notices.values())

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


# ─── Diagnostics surfaced to the user ─────────────────────────────────────────
def _message_box(title: str, text: str):
    """Show a blocking native message box. Used for failures that happen BEFORE
    any window can render (e.g. the WebView2 runtime is missing) — at that point
    the in-window status banner isn't an option. No-op / prints off Windows."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            # MB_ICONERROR | MB_SETFOREGROUND
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10 | 0x10000)
            return
        except Exception:
            pass
    print(f"{title}: {text}", flush=True)


def _webview2_available() -> bool:
    """True if the Microsoft Edge WebView2 runtime is installed. pywebview's
    winforms backend renders every window through it; without it the windows
    silently never appear. Checked before window creation so we can tell the
    user instead of failing blank. Returns True off Windows / if the check
    itself fails (avoid false negatives that would block a working install)."""
    if not sys.platform.startswith("win"):
        return True
    try:
        import winreg
    except Exception:
        return True
    # The runtime registers a versioned client under EdgeUpdate. A non-empty,
    # non-zero "pv" under any of these locations means it's installed.
    CLIENT = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    locations = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{CLIENT}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{CLIENT}"),
        (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{CLIENT}"),
    ]
    for root, path in locations:
        try:
            with winreg.OpenKey(root, path) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
                if pv and pv not in ("", "0.0.0.0"):
                    return True
        except Exception:
            continue
    return False


# Active diagnostic notices, keyed by id. Mirrored here (not just pushed) so a
# window that loads AFTER a notice was raised can pull the current set on ready
# (see Api.get_pending_status) — otherwise an early "game not found" would be
# lost to the push/load race and the user would see a blank counter.
_status_notices: dict = {}


def _push_status(notice_id: str, level: str, text: str, detail: str = "", clear: bool = False):
    """Surface a diagnostic banner in the always-visible counter window (and the
    main window when shown). `notice_id` keys the banner so repeated calls update
    in place instead of stacking; pass clear=True to remove it. `level` is
    'info' | 'warn' | 'error'. Safe to call from any background thread."""
    notice = {"id": notice_id, "level": level, "text": text,
              "detail": detail, "clear": bool(clear)}
    if clear or (not text and not detail):
        _status_notices.pop(notice_id, None)
    else:
        _status_notices[notice_id] = notice
    payload = json.dumps(notice, ensure_ascii=False)
    js = f"window.onStatus && window.onStatus({payload})"
    for w in (_counter_win, _window):
        if w is None:
            continue
        try:
            w.evaluate_js(js)
        except Exception:
            pass


# ─── Pushing state to the UI ──────────────────────────────────────────────────
def push_state(view_model: dict):
    """Push a view-model dict to BOTH the main window and the counter window.

    Each window's `window.onState` picks the slices it cares about (the main
    window uses the full view-model; the counter window only reads
    `vm.counter.remaining` and `vm.round`).
    """
    global _live_connected
    if not _live_connected:
        # First live frame — we're definitely hooked into the game now, so
        # clear the "connecting…" banner. Done here (not in the frida setup)
        # because frida attaching ≠ the game actually streaming gameplay.
        _live_connected = True
        _push_status("frida", "info", "", clear=True)
    payload = json.dumps(view_model, ensure_ascii=False)
    js = f"window.onState && window.onState({payload})"
    # In counter-only mode the main window is hidden — don't push to it (skips
    # the now-invisible damage sim entirely).
    targets = (_counter_win,) if _counter_only else (_window, _counter_win)
    for w in targets:
        if w is None:
            continue
        try:
            w.evaluate_js(js)
        except Exception:
            pass


def push_best_lines(result: dict):
    """Push a best-line calc result (top lines + highlighted pick) to the main
    window's calc panel via window.onBestLines. Sent by the BestLineEngine on its
    own thread (fast then final stage). No-op until the panel's JS handler exists,
    so it's safe while the feature is still gated behind YX_BESTLINE."""
    if _window is None:
        return
    try:
        payload = json.dumps(result, ensure_ascii=False)
        _window.evaluate_js(f"window.onBestLines && window.onBestLines({payload})")
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
            kwargs={"path": path, "push_best_lines": push_best_lines},
            daemon=True, name="replay-ui",
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
            kwargs={"push_best_lines": push_best_lines},
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
    # If the game is ALREADY running, attach to it instead of spawning. This MUST
    # run even when game_exe is set (from YX_GAME_EXE or YiXianHUD_config.json),
    # otherwise we'd always spawn — and YiXianPai is single-instance via Steam, so
    # a spawned duplicate just exits and frida ends up hooking a dead process (the
    # "can't find the game when it's already open" bug). Attach wins over spawn.
    if not attach:
        try:
            import subprocess
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq YiXianPai.exe"],
                                 capture_output=True, text=True, timeout=10).stdout
            if "YiXianPai.exe" in out:
                attach = True
        except Exception:
            pass
    # Out-of-box fallback (esp. the packaged exe): not running and no exe known →
    # spawn the default Steam install.
    if not attach and not game_exe:
        default_exe = r"C:\Program Files (x86)\Steam\steamapps\common\YiXianPai\YiXianPai.exe"
        if Path(default_exe).exists():
            game_exe = default_exe

    # If we have neither a game to attach to nor a known exe to spawn, frida
    # has nothing to hook — tell the user instead of letting the thread die
    # silently with an empty counter. (Spawn/attach errors raised later are
    # surfaced by _frida_capture_guarded below.)
    if not attach and not game_exe:
        _push_status(
            "frida", "error",
            "找不到游戏 / Game not found",
            "未找到 YiXianPai。请先启动游戏（推荐），或确认游戏已安装。\n"
            "默认路径：C:\\Program Files (x86)\\Steam\\steamapps\\common\\YiXianPai\\\n"
            "若安装在其它位置，请设置环境变量 YX_GAME_EXE 指向 YiXianPai.exe。",
        )
    else:
        _push_status(
            "frida", "info",
            "正在连接游戏… / Connecting to game…",
            "启动 YiXianPai 后计数会自动开始。" if not attach
            else "已检测到运行中的游戏，正在挂接…",
        )

    def _frida_capture_guarded():
        """Run the frida capture and turn any setup failure into a user-visible
        banner. Without this the thread would die silently and the counter would
        just sit empty — the single most common 'it doesn't work' report."""
        try:
            runtime.start_frida_capture(game_exe=game_exe, attach_mode=attach)
        except FileNotFoundError as e:
            _push_status(
                "frida", "error", "找不到游戏 / Game not found",
                "未找到 YiXianPai 可执行文件。请先启动游戏，或设置 YX_GAME_EXE。\n"
                + str(e))
        except Exception as e:
            # Most often: frida injection blocked by antivirus/Defender, or the
            # game arch/version mismatched. Either way the counter can't get data.
            _push_status(
                "frida", "error", "无法挂接游戏 / Can't hook game",
                "frida 注入失败，通常是被杀毒软件 / Windows Defender 拦截。\n"
                "请把本程序加入杀毒白名单后重试。\n详情: " + str(e))
            import traceback
            print("[frida-capture EXCEPTION]\n" + traceback.format_exc(), flush=True)

    threading.Thread(
        target=_frida_capture_guarded,
        daemon=True, name="frida-capture",
    ).start()
    threading.Thread(
        target=runtime.start_consumer, args=(push_state,),
        kwargs={"push_best_lines": push_best_lines},
        daemon=True, name="consumer",
    ).start()
    # Yi Xian Oracle: sync its game data to the installed game (extract DLL/configs,
    # self-heal facades if the game's IL2CPP core changed), THEN warm the worker so
    # the first live matchup is instant. Runs on a background thread — the first run
    # / a post-patch run takes ~20-120s, but the UI stays responsive meanwhile.
    def _oracle_startup():
        try:
            sys.path.insert(0, str(BASE_DIR / "proxy"))
            import oracle_bootstrap
            status = oracle_bootstrap.ensure_current(game_exe)
            print(f"[oracle-sync] {status}", flush=True)
            # Surface engine/sync failures as a non-blocking warning — the deck
            # counter keeps working, but damage (伤害) and review (复盘) need the
            # engine, so the user should know if it didn't come up.
            _ok = {"synced", "already current"}
            if status not in _ok:
                if str(status).startswith("game install not found"):
                    # The frida 'game not found' error banner already covers the
                    # root cause; don't double up with a second message.
                    pass
                elif "download" in status or "checksum" in status:
                    _push_status(
                        "engine", "warn", "引擎下载失败 / Engine download failed",
                        "伤害与复盘功能需要联网下载引擎组件（约42MB）。\n"
                        "请检查网络连接（需可访问 gitee.com）后重启程序。\n卡牌计数不受影响。")
                else:
                    _push_status(
                        "engine", "warn", "引擎未就绪 / Engine not ready",
                        f"伤害与复盘暂不可用（{status}）。卡牌计数不受影响。\n"
                        "详情见 %LOCALAPPDATA%\\YiXianCounter\\oracle-sync.log")
            else:
                _push_status("engine", "info", "", clear=True)
            import oracle_sim
            oracle_sim.warmup()
        except Exception:
            # --windowed swallows stdout — log the traceback to a file.
            try:
                import os as _os, traceback as _tb
                lf = Path(_os.environ.get("LOCALAPPDATA", str(BASE_DIR))) / "YiXianCounter" / "oracle-sync.log"
                lf.parent.mkdir(parents=True, exist_ok=True)
                with lf.open("a", encoding="utf-8") as f:
                    f.write("STARTUP EXCEPTION:\n" + _tb.format_exc() + "\n")
            except Exception:
                pass
    threading.Thread(target=_oracle_startup, daemon=True, name="oracle-startup").start()


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


def _setup_frozen_logging():
    """The packaged exe is --windowed (no console), so stdout/stderr vanish and
    any startup exception is invisible. Redirect both to a log file so problems
    are diagnosable."""
    if not getattr(sys, "frozen", False):
        return
    try:
        log = Path(os.environ.get("LOCALAPPDATA", str(BASE_DIR))) / "YiXianCounter" / "app.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        f = open(log, "a", encoding="utf-8", buffering=1)
        sys.stdout = f
        sys.stderr = f
        import datetime
        print(f"\n=== launch {datetime.datetime.now():%Y-%m-%d %H:%M:%S} v{globals().get('__version__','?')} ===", flush=True)
    except Exception:
        pass


def main():
    global _window, _counter_win
    _setup_frozen_logging()
    # WebView2 renders the UI on the GPU. A freshly (re)installed or updated GPU
    # driver can destabilize its renderer process, which silently closes the window
    # — and since the counter is the MASTER window, that closes the whole app (a
    # clean exit, no traceback, mid-match). Disabling GPU compositing for the
    # WebView2 UI sidesteps this; the UI is trivial HTML so there's no visible cost,
    # and it does NOT touch the game's own (Unity) rendering. Override by setting
    # WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS yourself before launch.
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-gpu")
    # WebView2 is required to render any window. If it's missing, every
    # webview.create_window call would produce a blank/never-appearing window
    # with the failure buried in app.log — so the user sees "nothing happens".
    # Detect it up front and tell them exactly what to install.
    if not _webview2_available():
        _message_box(
            "YiXian Counter — 缺少运行库 / Missing runtime",
            "未检测到 Microsoft Edge WebView2 运行时，程序窗口无法显示。\n"
            "请从下方网址免费下载并安装，然后重新运行本程序：\n\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            "Microsoft Edge WebView2 Runtime is not installed, so the app "
            "windows cannot be displayed.\nInstall it (free) from the link "
            "above, then relaunch.",
        )
        return
    _patch_winforms_on_top()
    api = Api()
    # Counter window — deck counter + 复盘. Created FIRST so it's the master
    # (webview.windows[0]) and therefore always visible: in counter-only mode
    # the main window is hidden, and a hidden MASTER misbehaves on some backends.
    # Lite-style: small, frameless, always-on-top; counter.js auto-resizes it.
    _counter_win = webview.create_window(
        title="YiXian Counter — Cards Left",
        url=COUNTER_HTML.as_uri(),
        js_api=api,
        width=260,
        height=100,          # short start; counter.js auto-resizes to content
        x=420, y=40,
        frameless=True,
        easy_drag=False,
        on_top=api.settings.get("onTop", True),
        background_color="#11141a",
        # Lowered to match the lite window's MIN_SCALE=0.6: 260 * 0.6 = 156.
        min_size=(150, 30),
    )
    # Main window — round bar + damage calculator. Hidden in counter-only mode
    # (the live calc needs the Oracle engine, which the exe doesn't bundle). It
    # still exists so the shared js_api + update-notice plumbing keep working.
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
        # can actually shrink the window to a titlebar-only strip. Frameless
        # means the user can't drag-resize edges, so a small min is safe.
        min_size=(200, TITLEBAR_HEIGHT),
        hidden=_counter_only,
    )
    # Stash the Api on the window so _push_update_notice can write the
    # pending manifest back into it (avoids a re-fetch when the user clicks
    # "更新" on the banner).
    _window._js_api_instance = api
    # Open the WebView2 dev tools only when YX_DEVTOOLS is set — NOT on
    # YX_DEBUG (that one just enables battle_log storage), so the normal
    # debug/storage run doesn't pop dev tools every launch.
    def _start_workers_logged():
        try:
            _start_workers()
        except Exception:
            import traceback
            print("[_start_workers EXCEPTION]\n" + traceback.format_exc(), flush=True)
    webview.start(_start_workers_logged, debug=bool(os.environ.get("YX_DEVTOOLS")))


if __name__ == "__main__":
    main()
