# -*- coding: utf-8 -*-
"""Shared feed-writer used by every HUD/runtime path (feed_probe, hud_launcher,
tool_bridge). One feed.jsonl per RUNTIME SESSION goes under feeds/<ts>/ next
to whatever copy of BattleLog.json was current when the session ended.

Each line is one Colyseus event: {"dir": "in"|"out", "t": "<type>", "b": "<base64>"}
— the exact shape `addon.process_msgpack` expects when replayed.

The Review window's reader (game_archive._discover_feeds) finds unprocessed
feed.jsonl files and replays them through the addon dispatcher under
YX_DEBUG=1, materialising a battle_log/<game_ts>/ folder per StartGameResp.

Keep this module dependency-free (no addon import) so it's safe to import
anywhere in the HUD bootstrap path.
"""
from __future__ import annotations
import json, os, threading, datetime, shutil
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_FEEDS_ROOT = Path(os.environ.get("YX_FEEDS_ROOT", _REPO / "feeds"))
# Where the game stores its live BattleLog.json. Snapshotted at session end.
_GAME_BATTLELOG = (Path.home() / "AppData" / "LocalLow"
                   / "DarkSunStudio" / "YiXianPai" / "BattleLog.json")

_writer_lock = threading.Lock()
_writer_state = {"dir": None, "file": None, "ts": None, "count": 0}


def start_session() -> Path | None:
    """Open a fresh feeds/<ts>/feed.jsonl for the current runtime session.
    Returns the session folder, or None if disabled (YX_NO_FEED=1)."""
    if os.environ.get("YX_NO_FEED", "0") != "0":
        return None
    with _writer_lock:
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        d = _FEEDS_ROOT / ts
        d.mkdir(parents=True, exist_ok=True)
        f = open(d / "feed.jsonl", "w", encoding="utf-8")
        _writer_state["dir"] = d
        _writer_state["file"] = f
        _writer_state["ts"] = ts
        _writer_state["count"] = 0
        return d


def write_event(direction: str, type_name: str, b64: str) -> None:
    """Append one Colyseus event. Safe no-op if no session is open."""
    f = _writer_state["file"]
    if not f:
        return
    with _writer_lock:
        try:
            f.write(json.dumps({"dir": direction, "t": type_name, "b": b64},
                               ensure_ascii=False) + "\n")
            _writer_state["count"] += 1
            # Flush every 32 events so a hard-kill loses ≤ 1 round at most.
            if _writer_state["count"] % 32 == 0:
                f.flush()
        except Exception:
            pass


def snapshot_battle_log() -> None:
    """Copy the game's current BattleLog.json into the session folder so the
    reader has authoritative per-round HP / usedCards alongside the feed."""
    d = _writer_state["dir"]
    if not d or not _GAME_BATTLELOG.exists():
        return
    try:
        shutil.copy2(_GAME_BATTLELOG, d / "battle_log.json")
    except Exception:
        pass


def end_session() -> None:
    """Flush + close the feed file. Idempotent."""
    with _writer_lock:
        f = _writer_state["file"]
        if f:
            try:
                f.flush()
                f.close()
            except Exception:
                pass
        _writer_state["file"] = None
    snapshot_battle_log()


def session_dir() -> Path | None:
    return _writer_state["dir"]
