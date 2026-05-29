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


class Api:
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


def _start_workers():
    import runtime
    threading.Thread(target=runtime.start_proxy, daemon=True, name="proxy").start()
    threading.Thread(
        target=runtime.start_consumer, args=(push_state,), daemon=True, name="consumer"
    ).start()


def main():
    global _window
    _window = webview.create_window(
        title="YiXian Counter (Lite)",
        url=INDEX_HTML.as_uri(),
        js_api=Api(),
        width=260,
        height=70,                 # tiny default — JS will grow it as cards arrive
        frameless=True,
        easy_drag=False,
        on_top=True,
        background_color="#11141a",
        min_size=(200, 40),        # let JS shrink the window down to ~titlebar height
    )
    webview.start(_start_workers, debug=bool(os.environ.get("YX_DEBUG")))


if __name__ == "__main__":
    main()
