"""
YiXian Counter (Lite)
─────────────────────
Standalone Windows build that shows ONLY the "cards left in deck"
counter — no damage sim, no hand/board, no opponent.

Build: see `build.bat` / `build.py` in this folder.
Run:   YiXianCounterLite.exe   (requires admin for mitmproxy local mode)
"""
import json
import os
import sys
import threading
from pathlib import Path

# YiXianCounterLite never produces battle_log/ debug folders. Strip any
# leaked YX_DEBUG env var before importing addon so the per-game folder
# rotation stays dormant in the lite build.
os.environ.pop("YX_DEBUG", None)

import webview


def _base_dir() -> Path:
    """Resolve the runtime base — both source mode and PyInstaller one-file."""
    if getattr(sys, "frozen", False):
        # PyInstaller one-file extracts to _MEIPASS; for the WEB dir we
        # want the extracted bundle, but for any writable state we use
        # the EXE's parent. Here all assets are read-only.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
WEB_DIR = BASE_DIR / "web"
INDEX_HTML = WEB_DIR / "index.html"

# Wire proxy/ as an import path so `import addon` etc. works the same way
# as the parent project's runtime.
PROXY_DIR = BASE_DIR / "proxy"
if str(PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(PROXY_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


_window = None


def _settings_path() -> Path:
    """Per-user JSON file for the lite's persisted settings (UI scale, etc.).
    Lives in %APPDATA% so it survives exe reinstalls + auto-updates."""
    base = os.environ.get("APPDATA") or str(BASE_DIR)
    d = Path(base) / "yixian-counter-lite"
    d.mkdir(parents=True, exist_ok=True)
    return d / "settings.json"


_DEFAULT_LITE_SETTINGS = {"uiScale": 1.0}


def _load_lite_settings() -> dict:
    p = _settings_path()
    if p.exists():
        try:
            return {**_DEFAULT_LITE_SETTINGS, **json.loads(p.read_text(encoding="utf-8"))}
        except Exception:
            pass
    return dict(_DEFAULT_LITE_SETTINGS)


def _save_lite_settings(settings: dict):
    try:
        _settings_path().write_text(
            json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


class Api:
    def __init__(self):
        self.settings = _load_lite_settings()

    def get_settings(self):
        return self.settings

    def set_setting(self, key, value):
        self.settings[key] = value
        _save_lite_settings(self.settings)
        return self.settings

    def get_version(self):
        """Return the bundled VERSION string. JS shows it in the titlebar."""
        try:
            from version import VERSION
            return VERSION
        except Exception:
            return "?"

    def start_update(self):
        """Called from JS when the user clicks "Update now" on the banner.
        Downloads the new exe, verifies SHA256, schedules the swap-and-relaunch
        via a tiny .bat helper, then exits this process.

        Returns a result dict so the UI can show a message on failure
        ({'ok': True} on success — but the process is about to die so the JS
        will never actually receive that response)."""
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
        # Give the bat helper a moment to start, then exit so it can swap
        # the file. The main thread is the webview event loop; tear it down.
        import threading
        import time
        def _quit():
            time.sleep(0.4)
            try:
                if _window is not None:
                    _window.destroy()
            except Exception:
                pass
            os._exit(0)
        threading.Thread(target=_quit, daemon=True).start()
        return {"ok": True}

    def move(self, x, y):
        """Move the window's top-left to (x, y) in screen pixels.

        Called from the JS title-bar drag handler — WebView2 ignores the
        -webkit-app-region CSS, so dragging is implemented manually.
        """
        if _window is not None:
            try:
                _window.move(int(x), int(y))
            except Exception:
                pass

    def resize(self, w, h):
        """Resize the window to (w, h). Called from JS after each render so
        the window auto-fits the counter contents (1 row vs 8 rows ≠ same
        height)."""
        if _window is not None:
            try:
                _window.resize(int(w), int(h))
            except Exception:
                pass

    def quit(self):
        if _window is not None:
            _window.destroy()


def push_state(view_model: dict):
    """Strip the view-model down to just round + counter before pushing."""
    if _window is None:
        return
    slim = {
        "round": view_model.get("round"),
        "counter": view_model.get("counter") or {},
    }
    payload = json.dumps(slim, ensure_ascii=False)
    js = f"window.onState && window.onState({payload})"
    try:
        _window.evaluate_js(js)
    except Exception:
        pass


def _push_update_notice(manifest: dict):
    """Notify the JS UI that an update is available. Called from the
    updater's background thread; window.evaluate_js is thread-safe enough
    for this simple JSON push."""
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
    # Stash the manifest so Api.start_update() doesn't re-check the network.
    api = getattr(_window, "_js_api_instance", None)
    if api is not None:
        api._pending_update = manifest


def _start_workers():
    import runtime
    threading.Thread(target=runtime.start_proxy, daemon=True, name="proxy").start()
    threading.Thread(
        target=runtime.start_consumer, args=(push_state,), daemon=True, name="consumer"
    ).start()
    # Auto-update: check Gitee once on startup. Doesn't block — short timeout
    # and runs on its own thread so a slow / offline network never delays the
    # window opening. When a newer version is found, notifies the JS banner.
    try:
        import updater
        updater.check_for_update_async(_push_update_notice)
    except Exception:
        pass


def main():
    global _window
    api = Api()
    _window = webview.create_window(
        title="YiXian Counter (Lite)",
        url=INDEX_HTML.as_uri(),
        js_api=api,
        width=260,
        height=70,                 # tiny default — JS will grow it as cards arrive
        frameless=True,
        easy_drag=False,
        on_top=True,
        background_color="#11141a",
        min_size=(200, 40),        # let JS shrink the window down to ~titlebar height
    )
    # Stash the Api on the window so _push_update_notice can write the
    # pending manifest back into it (avoids a re-fetch when the user clicks
    # "update now" on the banner).
    _window._js_api_instance = api
    webview.start(_start_workers, debug=bool(os.environ.get("YX_DEBUG")))


if __name__ == "__main__":
    main()
