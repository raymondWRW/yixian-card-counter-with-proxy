"""
Auto-update for the main YiXian Counter app — Gitee-backed, SHA256-verified,
prompt-first. Mirrors small_card_counter/updater.py but targets the main
app's own manifest file (dist_share/version.json) and exe filename.

Both apps live in the same Gitee repo. They don't collide because:
  - Main app pulls from dist_share/version.json
  - Lite app pulls from small_card_counter/dist_share/version.json
  - Main releases use tag prefix `main-v…`, lite uses `lite-v…`

See small_card_counter/updater.py for the deeper design discussion.
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
GITEE_USER = "hiddensquid12321"
GITEE_REPO = "yixian-card-counter-with-proxy"
GITEE_BRANCH = "master"
# Manifest for the MAIN app lives at the repo root's dist_share/.
MANIFEST_URL = (
    f"https://gitee.com/{GITEE_USER}/{GITEE_REPO}/raw/"
    f"{GITEE_BRANCH}/dist_share/version.json"
)
EXE_FILENAME = "YiXianCounter.exe"

CHECK_TIMEOUT = 5
DOWNLOAD_TIMEOUT = 120  # main bundle is larger than the lite — give it room


def _parse_version(v: str) -> tuple:
    parts = []
    for p in str(v or "").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _http_json(url: str, timeout: float) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "YiXianCounter"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, json.JSONDecodeError, ValueError, OSError):
        return None


def _current_version() -> str:
    try:
        from version import VERSION
        return VERSION
    except Exception:
        return "0.0.0"


def check_for_update() -> dict | None:
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
    url = manifest["url"]
    expected_sha = str(manifest["sha256"]).lower()
    tmp = Path(tempfile.gettempdir()) / f"YiXianCounter_new_{os.getpid()}.exe"
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "YiXianCounter"})
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
    target = _exe_dir() / EXE_FILENAME
    if not target.exists() and getattr(sys, "frozen", False):
        target = Path(sys.executable)
    bat_path = Path(tempfile.gettempdir()) / f"yixian_main_update_{os.getpid()}.bat"
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
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        close_fds=True,
    )


def check_for_update_async(on_found):
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
