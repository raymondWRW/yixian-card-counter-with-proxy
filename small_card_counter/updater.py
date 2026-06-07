"""
Auto-update for YiXianCounterLite — Gitee-backed, SHA256-verified, prompt-first.

Flow on app launch:
  1. `check_for_update()` fetches MANIFEST_URL (a small JSON on Gitee Raw).
     Short timeout so an offline / slow network doesn't block startup.
  2. If the manifest's `version` is newer than the bundled `version.VERSION`,
     it returns the parsed manifest dict (else None).
  3. The UI surfaces an "Update available" banner. When the user clicks it,
     JS calls back into Api.start_update() which downloads the new exe,
     verifies SHA256, writes an updater.bat, launches it, and exits.
  4. updater.bat sleeps long enough for the old exe to release its file
     lock, then `move /Y` swaps the new exe over the old and relaunches.

China-accessibility: Gitee is the recommended endpoint (no GitHub/CDN
dependency). The Raw + Releases URLs both resolve fast from mainland China.

CONFIGURE BEFORE RELEASE:
  - GITEE_USER and GITEE_REPO below (your gitee.com username + repo name)
  - The exe filename if you renamed it from YiXianCounterLite.exe
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

# ─── Configuration ─────────────────────────────────────────────────────────
# Replace with YOUR Gitee account + repo. The raw URL needs to resolve to a
# version.json that matches the schema in `EXAMPLE_MANIFEST` below.
GITEE_USER = "hiddensquid12321"
GITEE_REPO = "yixian-card-counter-with-proxy"
# Gitee usually keeps "master" as the default branch even when GitHub uses
# "main". Check your Gitee repo's default branch and adjust if needed.
GITEE_BRANCH = "master"
# Where the version manifest lives in the repo. The Raw URL bypasses Gitee's
# HTML rendering and serves the file as-is, which is what we want.
MANIFEST_URL = (
    f"https://gitee.com/{GITEE_USER}/{GITEE_REPO}/raw/"
    f"{GITEE_BRANCH}/small_card_counter/dist_share/version.json"
)
# Filename of the running exe. Updater.bat replaces THIS file with the new
# download. Must match the actual filename used at distribution time.
EXE_FILENAME = "YiXianCounterLite.exe"

# Network timeouts. Short on the check (don't delay startup if offline);
# longer on the download (the binary is ~20-30 MB).
CHECK_TIMEOUT = 5      # seconds
DOWNLOAD_TIMEOUT = 60  # seconds for the whole download
# A "version" string is treated as newer if its tuple is lexicographically
# greater. This requires plain dotted-number versions (e.g. 1.2.3) without
# pre-release suffixes — keep the scheme simple.

EXAMPLE_MANIFEST = {
    "version": "1.0.1",
    "url": "https://gitee.com/USER/yixian-counter/releases/download/v1.0.1/YiXianCounterLite.exe",
    "sha256": "0123abcdef…",
    "notes": "What changed in this release",
}


def _parse_version(v: str) -> tuple:
    """Parse '1.2.3' → (1, 2, 3). Non-numeric components become 0."""
    parts = []
    for p in str(v or "").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _http_json(url: str, timeout: float) -> dict | None:
    """Fetch a small JSON document. Returns None on any failure (offline,
    timeout, bad JSON, non-200) — the auto-update is best-effort and must
    never crash the app."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "YiXianCounterLite"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, json.JSONDecodeError, ValueError, OSError):
        return None


def _current_version() -> str:
    """Read the bundled version string. Defaults to '0.0.0' if version.py
    can't be imported (e.g. dev runs outside the bundle)."""
    try:
        from version import VERSION
        return VERSION
    except Exception:
        return "0.0.0"


def check_for_update() -> dict | None:
    """Return the manifest dict if a newer version is published, else None.
    Never raises — safe to call on startup from any thread."""
    manifest = _http_json(MANIFEST_URL, CHECK_TIMEOUT)
    if not isinstance(manifest, dict):
        return None
    remote_v = manifest.get("version")
    if not remote_v:
        return None
    if _parse_version(remote_v) <= _parse_version(_current_version()):
        return None
    if not manifest.get("url") or not manifest.get("sha256"):
        return None
    return manifest


def _exe_dir() -> Path:
    """Folder that contains the running .exe (or app.py in dev mode)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _sha256_file(path: Path, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def download_update(manifest: dict, progress_cb=None) -> Path:
    """Download the new exe to a temp file and verify SHA256.

    Returns the path to the downloaded exe on success. Raises RuntimeError
    on any failure (download error, hash mismatch, etc.) — the UI catches
    and shows the error to the user.
    """
    url = manifest["url"]
    expected_sha = str(manifest["sha256"]).lower()

    tmp = Path(tempfile.gettempdir()) / f"YiXianCounterLite_new_{os.getpid()}.exe"
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "YiXianCounterLite"})
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            seen = 0
            with tmp.open("wb") as out:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
                    seen += len(chunk)
                    if progress_cb and total:
                        try:
                            progress_cb(seen, total)
                        except Exception:
                            pass
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"download failed: {e}")

    actual_sha = _sha256_file(tmp)
    if actual_sha.lower() != expected_sha:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise RuntimeError(
            f"SHA256 mismatch (expected {expected_sha[:12]}…, got {actual_sha[:12]}…)"
        )
    return tmp


def apply_update(new_exe_path: Path) -> None:
    """Schedule the file swap via a tiny .bat helper, then exit.

    Windows holds a file lock on the running .exe so we can't overwrite it
    in-process. The .bat waits a couple seconds for our process to exit,
    then `move /Y` swaps the new exe over the old and relaunches it.
    """
    target = _exe_dir() / EXE_FILENAME
    if not target.exists() and getattr(sys, "frozen", False):
        # In dev mode (frozen=False) we don't replace anything — just exit.
        target = Path(sys.executable)

    bat_path = Path(tempfile.gettempdir()) / f"yixian_update_{os.getpid()}.bat"
    # `>nul 2>&1` swallows the timeout/move output. The `del "%~f0"` at the
    # end deletes the bat itself once swap is done.
    bat = (
        "@echo off\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'move /Y "{new_exe_path}" "{target}" >nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        "  timeout /t 3 /nobreak >nul\r\n"
        f'  move /Y "{new_exe_path}" "{target}" >nul 2>&1\r\n'
        ")\r\n"
        f'start "" "{target}"\r\n'
        'del "%~f0"\r\n'
    )
    bat_path.write_text(bat, encoding="ascii")

    # CREATE_NO_WINDOW (0x08000000) hides the cmd window briefly flashing.
    # DETACHED_PROCESS (0x00000008) makes the bat outlive our process.
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        close_fds=True,
    )


def check_for_update_async(on_found):
    """Run check_for_update() on a background thread; when an update is
    available, call `on_found(manifest)` on that same thread. The caller is
    responsible for marshalling back to the UI thread (we just push JSON
    through window.evaluate_js which is thread-safe enough for pywebview)."""
    def _worker():
        try:
            manifest = check_for_update()
        except Exception:
            manifest = None
        if manifest:
            try:
                on_found(manifest)
            except Exception:
                pass
    threading.Thread(target=_worker, daemon=True, name="updater-check").start()
