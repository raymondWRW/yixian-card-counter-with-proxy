"""
convert_feed.py
──────────────
Replay a HUD session's feeds/<ts>/feed.jsonl through addon.process_msgpack
under YX_DEBUG=1, materialising one battle_log/<game_ts>/ folder per
StartGameResp the feed contains. The Review window then sees these games
through the existing game_archive.list_games() path.

Idempotent: skips any feed whose marker file already exists.

Usage:
  python tools/convert_feed.py              # convert every new feed
  python tools/convert_feed.py <feed_path>  # convert one specifically
"""
from __future__ import annotations
import json, os, sys, shutil, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FEEDS = Path(os.environ.get("YX_FEEDS_ROOT", REPO / "feeds"))
BATTLE_LOG = REPO / "battle_log"
DONE_MARKER = ".converted"

# Force DEBUG=1 BEFORE importing addon so its module-level DEBUG check fires
# True. addon.process_msgpack on StartGameResp then opens a battle_log/<ts>/
# folder automatically and routes shadow_log / deck_tracker / msgdump there.
os.environ["YX_DEBUG"] = "1"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "proxy"))

import addon  # noqa: E402
import shadow_state  # noqa: E402


def reset_addon_state() -> None:
    """Clear every module-level cache so replaying multiple feeds doesn't
    leak state across sessions. Mirrors what StartGameResp does internally
    plus the cross-game globals (reroll_events, chosen_*)."""
    addon.reroll_events.clear()
    addon.chosen_fates.clear()
    addon.chosen_derivations.clear()
    addon.daoyun_grant_events.clear()
    shadow_state.shadow = None
    shadow_state.clear_pending_choice()
    shadow_state.last_career_pick = 0


def replay_feed(feed_path: Path) -> list[Path]:
    """Replay one feed.jsonl. Returns the list of battle_log/<ts>/ folders
    that addon opened during the replay."""
    opened: list[Path] = []
    prev_dir = None
    reset_addon_state()
    with feed_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            t = ev.get("t")
            b = ev.get("b")
            d = ev.get("dir", "in")
            if not t or b is None:
                continue
            try:
                addon.process_msgpack(["data", {"type": t, "data": b}],
                                      from_client=(d == "out"))
            except Exception as e:
                print(f"  [warn] {t}: {e}", flush=True)
            # Track each new folder addon opens
            cur = addon._battle_log_dir
            if cur is not None and cur != prev_dir:
                opened.append(cur)
                prev_dir = cur
    # Flush any in-flight buffered logs to disk.
    try:
        addon._copy_battle_log_into_dir()
    except Exception:
        pass
    return opened


def copy_snapshot_battle_log(session_dir: Path,
                             opened_dirs: list[Path]) -> None:
    """If the session has its own battle_log.json snapshot (saved by
    _feed_writer.snapshot_battle_log at session end), drop it into the LAST
    game folder addon opened — that's the game the snapshot reflects."""
    snap = session_dir / "battle_log.json"
    if not snap.exists() or not opened_dirs:
        return
    target = opened_dirs[-1] / "battle_log.json"
    # Don't clobber a battle_log.json the addon already wrote (it would have
    # used the live in-game file — but replays don't have access to that, so
    # the addon's _copy_battle_log_into_dir would have done nothing). The
    # snapshot is always more authoritative than nothing.
    if target.exists() and target.stat().st_size > 0:
        return
    try:
        shutil.copy2(snap, target)
    except Exception:
        pass


def discover_feeds() -> list[Path]:
    """Return every feeds/<ts>/feed.jsonl that hasn't been converted yet."""
    if not FEEDS.exists():
        return []
    out = []
    for d in sorted(FEEDS.iterdir()):
        if not d.is_dir():
            continue
        f = d / "feed.jsonl"
        if not f.exists() or f.stat().st_size == 0:
            continue
        if (d / DONE_MARKER).exists():
            continue
        out.append(f)
    return out


def convert(feed_path: Path) -> int:
    """Convert one feed; mark done; return the count of games materialised."""
    print(f"[convert] {feed_path}", flush=True)
    opened = replay_feed(feed_path)
    copy_snapshot_battle_log(feed_path.parent, opened)
    (feed_path.parent / DONE_MARKER).write_text(
        f"converted at {datetime.datetime.now().isoformat()}\n"
        f"opened: {len(opened)}\n" +
        "\n".join(str(p) for p in opened),
        encoding="utf-8",
    )
    for p in opened:
        print(f"  → {p.name}", flush=True)
    return len(opened)


def main() -> int:
    targets: list[Path]
    if len(sys.argv) > 1:
        targets = [Path(a) for a in sys.argv[1:]]
    else:
        targets = discover_feeds()
        if not targets:
            print("No new feeds to convert.", flush=True)
            return 0
    total = 0
    for t in targets:
        try:
            total += convert(t)
        except Exception as e:
            print(f"[err] {t}: {e}", flush=True)
    print(f"\nConverted {len(targets)} feed(s) → {total} game(s).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
