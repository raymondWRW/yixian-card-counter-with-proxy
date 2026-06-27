"""
game_archive.py — discover and load past games recorded by the card counter.

The game itself doesn't keep per-game archives (its local BattleLog.json only
holds the CURRENT game). So all the review feature has to work with is what we
saved while running. Two formats coexist in `battle_log/`:

1. **Folder games** (older)  — `battle_log/YYYY-MM-DD_HHMMSS/` with
   `battle_log.json` (the game's per-round log, snapshotted at game end) plus
   `deck_tracker.jsonl` (our view-model per push) and `msgdump.jsonl` (raw wire
   frames). Character/sect comes from `battle_log.json`; sidejob/career from
   `msgdump.jsonl::SelectCareerReq`.

2. **Per-round games** (newer) — `battle_log/HHMMSS_rN.json`, one file per
   round, with ME + OPPONENT state, fates, slots, and the battle-result delta
   (br_pb5_hp_diff). Grouped by HHMMSS prefix.

Public API:
  list_games() -> [GameSummary]
  load_game(game_id) -> GameDetail
"""
from __future__ import annotations

import base64
import datetime
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATTLE_LOG = ROOT / "battle_log"

CAREER_NAMES = {1: "炼丹师", 2: "符箓师", 3: "琴师", 4: "画师",
                5: "阵法师", 6: "植灵师", 7: "卜算师"}

# Minimum rounds for a folder to count as a real, reviewable game. Real games
# never end before ~round 13 (you can't drain a 100-life pool sooner), so any
# folder with fewer rounds is a partial/aborted capture, not a game to review.
MIN_REAL_ROUNDS = 5

# Character name → wiki character_id (loaded from proxy/character_map.json).
_CHAR_MAP_PATH = Path(__file__).resolve().parent / "character_map.json"
_char_map_cache = None

# Sect name (English wiki form) → numeric ID for sect badge. The wiki's BL
# uses English sect names like "Cloud Spirit Sword Sect"; map to badge id.
_SECT_NAME_TO_ID = {
    "云灵剑宗": 1, "Cloud Spirit Sword Sect": 1,
    "锻玄宗": 2, "Duan Xuan Sect": 2,
    "七星阁": 3, "Heptastar Pavilion": 3,
    "五行山": 4, "五行道盟": 4, "Five Elements Alliance": 4,
}


def _char_map() -> dict:
    global _char_map_cache
    if _char_map_cache is None:
        try:
            _char_map_cache = json.loads(_CHAR_MAP_PATH.read_text(encoding="utf-8"))
        except Exception:
            _char_map_cache = {"name_to_id": {}, "name_to_sect": {}}
    return _char_map_cache


_WEB_CHARS = ROOT / "web" / "assets" / "characters"


def _char_asset(cid, suffix: str) -> str | None:
    """Web-relative URL of a character asset, but only if the PNG actually
    exists — so a newly-added character without art yet (e.g. 翎羽/4000006)
    falls back to a placeholder instead of showing a broken image."""
    if not cid:
        return None
    rel = f"assets/characters/{cid}-{suffix}.png"
    return rel if (_WEB_CHARS / f"{cid}-{suffix}.png").exists() else None


def _character_avatar(name: str) -> str | None:
    """Web-relative URL of the character's avatar, or None if unknown/missing."""
    return _char_asset(_char_map().get("name_to_id", {}).get(name), "avatar")


def _character_portrait(name: str) -> str | None:
    """Full-body portrait (408x660) — used as a hero image / hover preview."""
    return _char_asset(_char_map().get("name_to_id", {}).get(name), "portrait")


# Sect → accent color (drawn from each sect's signature palette in the wiki).
_SECT_ACCENTS = {
    1: "#7fa9d6",  # 云灵剑宗 — cloud blue
    2: "#b58263",  # 锻玄宗 — bronze
    3: "#c5a85e",  # 七星阁 — gold
    4: "#7fb682",  # 五行山 — green
}


def _sect_accent(sect_name: str) -> str | None:
    sid = _SECT_NAME_TO_ID.get(sect_name)
    return _SECT_ACCENTS.get(sid) if sid else None


def _sect_icon(sect_name: str) -> str | None:
    sid = _SECT_NAME_TO_ID.get(sect_name)
    return f"assets/sects/sect_badge_{sid}.png" if sid else None


def _sidejob_badge(career_id: int) -> str | None:
    if not career_id:
        return None
    return f"assets/side-jobs/side_job_badge_{career_id}.png"


# ─── Folder-format helpers ────────────────────────────────────────────────────
def _read_bl_jsonl(path: Path) -> list[dict]:
    """battle_log.json is JSONL with a leading file-size marker line."""
    out = []
    if not path.exists():
        return out
    try:
        for line in path.open("r", encoding="utf-8"):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        pass
    return out


def _me_username_from_msgdump(msgdump: Path) -> str | None:
    """ME's username + uid come from the team_container in GameStatus.
    Use the wire so the result matches what battle_log.json's `username` is.

    Fallback: if msgdump.jsonl is missing (e.g. a partial recovery from
    proxy/output/shadow_log.txt), look for a `me_username.txt` sibling file
    so the folder still resolves an owner.
    """
    if not msgdump.exists():
        # Fallback marker for partial-recovery folders.
        marker = msgdump.parent / "me_username.txt"
        if marker.exists():
            try:
                txt = marker.read_text(encoding="utf-8").strip()
                if txt:
                    return txt
            except Exception:
                pass
        return None
    try:
        import blackboxprotobuf
    except Exception:
        return None
    me_uid = None
    for line in msgdump.open("r", encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        mp = d.get("decoded", {}).get("msgpack", [None, None])
        if not isinstance(mp[1], dict) or mp[1].get("type") != "GameStatus":
            continue
        b64 = mp[1].get("data", "")
        if not b64:
            continue
        try:
            raw = base64.b64decode(b64)
            pb, _ = blackboxprotobuf.decode_message(raw)
        except Exception:
            continue
        f6 = pb.get("6")
        if isinstance(f6, dict):
            uid = f6.get("200")
            if isinstance(uid, (bytes, bytearray)) and len(uid) == 24:
                me_uid = bytes(uid).decode("utf-8", "replace")
                break
    if not me_uid:
        return None
    # Find the player whose UID matches in pb[5]
    for line in msgdump.open("r", encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        mp = d.get("decoded", {}).get("msgpack", [None, None])
        if not isinstance(mp[1], dict) or mp[1].get("type") != "GameStatus":
            continue
        b64 = mp[1].get("data", "")
        try:
            raw = base64.b64decode(b64)
            pb, _ = blackboxprotobuf.decode_message(raw)
        except Exception:
            continue
        for p in pb.get("5", []) or []:
            if not isinstance(p, dict):
                continue
            uid_b = p.get("1", b"")
            if not isinstance(uid_b, (bytes, bytearray)):
                continue
            if bytes(uid_b).decode("utf-8", "replace") != me_uid:
                continue
            nm_b = p.get("2", b"")
            if isinstance(nm_b, (bytes, bytearray)):
                return nm_b.decode("utf-8", "replace")
    return None


def _me_username_via_board(folder: Path, bl_records: list[dict] | None = None) -> str | None:
    """Fallback me-name resolver for frida-captured folders.

    The frida/native-HUD capture path writes an EMPTY msgdump.jsonl (it doesn't
    dump raw wire frames), so `_me_username_from_msgdump` can't identify ME for
    those games. But deck_tracker.jsonl records OUR board every round, and
    battle_log.json records every player's `usedCards`. Match our board's card
    names against each BL player's usedCards (summed over all rounds) and return
    the highest-overlap username — the same overlap trick `build_review_payload`
    uses to identify the opponent.
    """
    states = extract_round_states(folder)
    if not states:
        return None
    if bl_records is None:
        bl_records = _read_bl_jsonl(folder / "battle_log.json")
    if not bl_records:
        return None
    # Our board card-name set per round, from the deck_tracker snapshots.
    me_names_by_round: dict[int, set] = {}
    for rn, vm in states.items():
        names = {c.get("name") for c in ((vm.get("me") or {}).get("board") or [])
                 if isinstance(c, dict) and c.get("name")}
        if names:
            me_names_by_round[rn] = names
    if not me_names_by_round:
        return None
    overlap: dict[str, int] = {}
    for rec in bl_records:
        me_set = me_names_by_round.get(rec.get("round"))
        if not me_set:
            continue
        for p in rec.get("players", []):
            nm = p.get("username")
            if not nm:
                continue
            used = {c.get("name") for c in (p.get("usedCards") or [])
                    if isinstance(c, dict) and c.get("name")}
            if used:
                overlap[nm] = overlap.get(nm, 0) + len(me_set & used)
    if not overlap:
        return None
    best = max(overlap, key=overlap.get)
    return best if overlap[best] > 0 else None


def _resolve_me_name(folder: Path, bl_records: list[dict] | None = None) -> str | None:
    """Identify ME for a folder game. Tries msgdump.jsonl (+ me_username.txt
    marker) first; falls back to board-matching against battle_log.json for
    frida-captured folders whose msgdump.jsonl is empty."""
    name = _me_username_from_msgdump(folder / "msgdump.jsonl")
    if name:
        return name
    return _me_username_via_board(folder, bl_records)


def _derivations_from_msgdump(msgdump: Path) -> list[int]:
    """Scan msgdump.jsonl for `SimpleClientPact code=47` picks (the
    derivation / 天衍 picks). Returns a deduplicated list in pick order."""
    if not msgdump.exists():
        return []
    try:
        import blackboxprotobuf
    except Exception:
        return []
    out: list[int] = []
    for line in msgdump.open("r", encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        mp = d.get("decoded", {}).get("msgpack", [None, None])
        if not isinstance(mp[1], dict) or mp[1].get("type") != "SimpleClientPact":
            continue
        b64 = mp[1].get("data", "")
        if not b64:
            continue
        try:
            raw = base64.b64decode(b64)
            pb, _ = blackboxprotobuf.decode_message(raw)
        except Exception:
            continue
        if pb.get("1") != 47:
            continue
        did = pb.get("2")
        try:
            did_i = int(did)
        except (TypeError, ValueError):
            continue
        if did_i and did_i not in out:
            out.append(did_i)
    return out


def _career_pick_from_msgdump(msgdump: Path) -> int | None:
    """Find ME's SelectCareerReq (sent once at R2 sidejob pick)."""
    if not msgdump.exists():
        return None
    try:
        import blackboxprotobuf
    except Exception:
        return None
    for line in msgdump.open("r", encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        mp = d.get("decoded", {}).get("msgpack", [None, None])
        if not isinstance(mp[1], dict) or mp[1].get("type") != "SelectCareerReq":
            continue
        b64 = mp[1].get("data", "")
        try:
            raw = base64.b64decode(b64)
            pb, _ = blackboxprotobuf.decode_message(raw)
        except Exception:
            continue
        c = pb.get("1")
        if isinstance(c, int) and 1 <= c <= 7:
            return c
    return None


def _elimination_round(records: list[dict]) -> int | None:
    """Return the round in which the player was eliminated, or None if they
    survived to the end (still alive in the FINAL BL record).

    Detection signal: after elimination, BL freezes (life, lifeDelta,
    opponentUsername) — every subsequent round repeats them exactly. A
    survivor's records still change because the matchmaker keeps picking
    fresh opponents AND their state (life/delta) varies as battles happen.

    The `opponentUsername` is the strongest tiebreaker: a survivor's opponent
    changes every round, while an eliminated player's "last opponent" gets
    repeated as a placeholder until the game ends.

    Walks BACKWARDS from the final record to find the longest run of
    identical (life, lifeDelta, opponentUsername). The first round of that
    run is the elimination round. A run of length 1 means survivor → None.
    """
    if not records:
        return None
    recs = sorted(records, key=lambda r: r.get("round") or 0)
    if len(recs) < 2:
        return None
    def key(r):
        return (r.get("life"), r.get("lifeDelta"), r.get("opponentUsername"))
    final_key = key(recs[-1])
    # Walk back to find the FIRST round of the run that ends with final_key.
    elim = recs[-1].get("round")
    for i in range(len(recs) - 2, -1, -1):
        if key(recs[i]) == final_key:
            elim = recs[i].get("round")
        else:
            break
    # If only the last round matches (no freeze at all), the player survived.
    if elim == recs[-1].get("round"):
        return None
    return elim


def _player_out_round(recs: list[dict]) -> int | None:
    """Round this player was knocked out, or None if still alive at capture end.

    `recs` is one player's per-round records (each with `round`, `life`,
    `lifeDelta`). `life` is the life at the START of the round; `lifeDelta` is
    that round's battle result (<=0). A player is eliminated the first round
    their POST-battle life (`life + lifeDelta`) hits 0 — authoritative, unlike
    the freeze heuristic. Players who never hit 0 are co-survivors (None); the
    caller ranks them by remaining life (so the final clash's loser, who ends
    with less life, ranks below its winner).
    """
    if not recs:
        return None
    for r in sorted(recs, key=lambda r: r.get("round") or 0):
        if (r.get("life") or 0) + (r.get("lifeDelta") or 0) <= 0:
            return r.get("round")
    return None


def _compute_placement(bl_records: list[dict], me_name: str) -> int | None:
    """Final placement (1 = best, 8 = first to die).

    Placement is simply the number of players still alive (including ME) the
    round ME is knocked out: first to die in an 8-player lobby → 8 alive →
    8th; last standing → never knocked out → 1st. Players who die the same
    round share that number — we don't split simultaneous deaths, because
    that never affects ME's own placement (ME is never in such a tie).
    """
    if not bl_records or not me_name:
        return None
    # Group each player's per-round (round, life, lifeDelta) records.
    by_player: dict[str, list[dict]] = {}
    for rec in bl_records:
        rn = rec.get("round")
        for p in rec.get("players", []):
            nm = p.get("username")
            if nm:
                by_player.setdefault(nm, []).append({
                    "round": rn, "life": p.get("life"),
                    "lifeDelta": p.get("lifeDelta")})
    if me_name not in by_player:
        return None

    outs = {nm: _player_out_round(recs) for nm, recs in by_player.items()}
    me_out = outs[me_name]
    if me_out is not None:
        # ME was knocked out: placement = players still alive that round =
        # everyone who went out that round or later (higher round number) plus
        # anyone still standing (out None), counting ME.
        return sum(1 for o in outs.values() if o is None or o >= me_out)
    # ME survived to the end of the capture. If the recording stopped before
    # the game actually finished, SEVERAL players are still alive — ME isn't
    # automatically 1st. Rank ME among those co-survivors by remaining
    # (post-battle) life: most life left = best placement. (Only when ME is the
    # sole survivor does this return 1 — the true winner.)
    def _post_life(recs):
        last = sorted(recs, key=lambda r: r.get("round") or 0)[-1]
        return (last.get("life") or 0) + (last.get("lifeDelta") or 0)
    survivors = sorted(
        (nm for nm, o in outs.items() if o is None),
        key=lambda nm: (_post_life(by_player[nm]), nm), reverse=True)
    return survivors.index(me_name) + 1


def _folder_game_summary(folder: Path) -> dict | None:
    """Build summary metadata for a `YYYY-MM-DD_HHMMSS/` folder."""
    bl_records = _read_bl_jsonl(folder / "battle_log.json")
    if not bl_records:
        return None
    msgdump = folder / "msgdump.jsonl"
    me_name = _resolve_me_name(folder, bl_records)

    # Find ME's per-round records in BL (matched by username).
    me_rounds = []
    if me_name:
        for rec in bl_records:
            for p in rec.get("players", []):
                if p.get("username") == me_name:
                    me_rounds.append({
                        "round": rec.get("round"),
                        "level": p.get("level"),
                        "maxHp": p.get("maxHp"),
                        "life": p.get("life"),
                        "tiPo": p.get("tiPo"),
                        "maxTiPo": p.get("maxTiPo"),
                        "exp": p.get("exp"),
                        "lifeDelta": p.get("lifeDelta"),
                        "character": p.get("character"),
                        "sect": p.get("sect"),
                        "opponentUsername": p.get("opponentUsername"),
                    })
                    break
    me_rounds.sort(key=lambda r: r["round"] or 0)
    # In-game 复盘 captures (where the player triggered the game's built-in
    # review feature) usually start at a non-1 round AND/OR have gaps in the
    # round sequence. Real games start at round 1 and are contiguous (modulo
    # the very rare network blip). Filter the obvious 复盘 captures out.
    if me_rounds:
        round_nums = [r["round"] or 0 for r in me_rounds]
        starts_at_one = round_nums[0] == 1
        contiguous = all(round_nums[i + 1] - round_nums[i] == 1
                         for i in range(len(round_nums) - 1))
        # A real game is captured from the start: it begins at round 1 and runs
        # contiguously (you can't be eliminated by round 2). Anything else is a
        # mid-game attach or an in-game 复盘 spectate — e.g. a lone round-16 BL
        # record, since the game's own BattleLog.json only persists the CURRENT
        # round. Those "1-2 round" entries are not games the user played
        # start-to-finish, so drop them. (Single-round records used to be
        # exempted as "partial recoveries" — that exemption is exactly what let
        # the fake games through.)
        if not (starts_at_one and contiguous):
            return None
    # Drop post-elimination "spectator" rounds where the player is dead but BL
    # keeps logging frozen state. Keep the elimination round itself (the round
    # they actually played and lost in).
    elim_round = _elimination_round(me_rounds)
    if elim_round is not None:
        me_rounds = [r for r in me_rounds if (r["round"] or 0) <= elim_round]
    placement = _compute_placement(bl_records, me_name)

    # Aggregate facts.
    character = next((r["character"] for r in me_rounds if r.get("character")),
                     "?")
    sect = next((r["sect"] for r in me_rounds if r.get("sect")), "?")
    career_id = _career_pick_from_msgdump(msgdump)
    sidejob = CAREER_NAMES.get(career_id, "?") if career_id else "?"
    derivation_ids = _derivations_from_msgdump(msgdump)

    rounds_played = len(me_rounds)
    # Drop incomplete captures: a real game can't end before ~round 13 (the
    # earliest observed elimination), since draining a 100-life pool takes many
    # rounds. A 1-3 round folder is a session the user started but the recording
    # stopped early (app quit / crash) — often a practice run vs 傀儡 bots with
    # everyone still near full life. Below MIN_REAL_ROUNDS, treat as "not a real
    # game" and hide it from review. (13 is the floor; 5 leaves a wide margin.)
    if rounds_played < MIN_REAL_ROUNDS:
        return None
    final = me_rounds[-1] if me_rounds else {}
    # Lost rounds: lifeDelta < 0 = took damage = lost the round's battle.
    lost = [r["round"] for r in me_rounds
            if isinstance(r.get("lifeDelta"), int) and r["lifeDelta"] < 0]

    return {
        "id": folder.name,
        "format": "folder",
        "path": str(folder),
        "ts": folder.name,
        "me_name": me_name or "",
        "character": character,
        "character_avatar": _character_avatar(character),
        "character_portrait": _character_portrait(character),
        "sect": sect,
        "sect_icon": _sect_icon(sect),
        "sect_accent": _sect_accent(sect),
        "sidejob": sidejob,
        "sidejob_badge": _sidejob_badge(career_id or 0),
        "career_id": career_id or 0,
        "rounds_played": rounds_played,
        "final_life": final.get("life"),
        "final_realm": final.get("level"),
        "placement": placement,
        "lost_rounds": lost,
        "derivations": derivation_ids,
    }


# ─── Per-round-format helpers ─────────────────────────────────────────────────
_PER_ROUND_RE = re.compile(r"^(\d{6})_r(\d+)\.json$")


def _per_round_games() -> dict[str, list[dict]]:
    """Group `HHMMSS_rN.json` files by HHMMSS prefix → list of round records."""
    by_sess: dict[str, list[dict]] = {}
    for p in BATTLE_LOG.glob("*_r*.json"):
        m = _PER_ROUND_RE.match(p.name)
        if not m:
            continue
        sess, rn = m.group(1), int(m.group(2))
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        data["_round"] = rn
        data["_file"] = str(p)
        by_sess.setdefault(sess, []).append(data)
    for v in by_sess.values():
        v.sort(key=lambda d: d["_round"])
    return by_sess


def _per_round_summary(sess: str, rounds: list[dict]) -> dict:
    """Summary for a session built from per-round files."""
    if not rounds:
        return None
    first = rounds[0]
    me = first.get("me") or {}
    me_name = me.get("displayName", "")
    # Lost rounds: br_pb5_hp_diff is the hp delta of pb[1] vs pb[2]; we need to
    # know which combatant ME is. br_pb1_is_me=True → diff>0 means ME won.
    lost = []
    for r in rounds:
        diff = r.get("br_pb5_hp_diff")
        is_pb1 = r.get("br_pb1_is_me", False)
        if not isinstance(diff, int):
            continue
        me_won = (diff > 0) if is_pb1 else (diff < 0)
        if not me_won:
            lost.append(r.get("round") or r.get("_round"))
    return {
        "id": sess,
        "format": "per_round",
        "path": str(BATTLE_LOG / f"{sess}_r*.json"),
        "ts": sess,
        "me_name": me_name,
        # Per-round files don't carry character/sect/sidejob — only displayName.
        "character": "?",
        "character_avatar": None,
        "character_portrait": None,
        "sect": "?",
        "sect_icon": None,
        "sect_accent": None,
        "sidejob": "?",
        "sidejob_badge": None,
        "career_id": 0,
        "rounds_played": len(rounds),
        "final_life": (rounds[-1].get("me") or {}).get("hp"),
        "final_realm": (rounds[-1].get("me") or {}).get("realm"),
        "placement": None,
        "lost_rounds": lost,
    }


# ─── Public API ───────────────────────────────────────────────────────────────
def _auto_convert_feeds() -> None:
    """Lazily convert any HUD-session feeds/<ts>/feed.jsonl that haven't been
    replayed yet, so games captured via the frida/HUD method appear in the
    Review window alongside the proxy-method games. Best-effort: silently
    skips if the converter or feeds directory isn't present."""
    feeds_root = ROOT / "feeds"
    if not feeds_root.exists():
        return
    pending = []
    for d in feeds_root.iterdir():
        if not d.is_dir():
            continue
        f = d / "feed.jsonl"
        if f.exists() and f.stat().st_size > 0 and not (d / ".converted").exists():
            pending.append(f)
    if not pending:
        return
    try:
        import subprocess, sys as _sys
        tool = ROOT / "tools" / "convert_feed.py"
        if not tool.exists():
            return
        # Run synchronously so the resulting battle_log/<ts>/ folders are
        # visible to the loop below.
        subprocess.run([_sys.executable, str(tool)], check=False, cwd=str(ROOT))
    except Exception as e:
        print(f"[game_archive] feed auto-convert skipped: {e}", flush=True)


_char_id_to_name_cache = None


def _char_name_from_id(cid) -> str | None:
    """Reverse the character_map's name_to_id (character id → display name)."""
    global _char_id_to_name_cache
    if _char_id_to_name_cache is None:
        _char_id_to_name_cache = {str(i): n
                                  for n, i in _char_map().get("name_to_id", {}).items()}
    return _char_id_to_name_cache.get(str(cid))


def _recent_game_summaries() -> list[dict]:
    """Summaries for the user's own games decoded from the game's
    recentBattleDatas (see proxy/recent_battles.py) — the authoritative,
    far-more-complete history. Each is enriched with character avatar / sect the
    same way folder games are. `ts_ms` is carried so list_games() can match a
    recorded battle_log folder (for the 查看 / 复盘 board detail)."""
    try:
        import recent_battles
        games = recent_battles.decode_recent_games()
    except Exception as e:
        print(f"[game_archive] recent decode skipped: {e}", flush=True)
        return []
    out = []
    sect_map = _char_map().get("name_to_sect", {})
    for g in games:
        name = _char_name_from_id(g.get("character_id")) or "?"
        sect = sect_map.get(name, "?") if name != "?" else "?"
        out.append({
            "id": g["start_local"],          # replaced by folder id if matched
            "format": "recent",
            "battle_id": g.get("battle_id"),
            "ts": g["start_local"],
            "ts_ms": g.get("ts_ms"),
            "me_name": g.get("me_name", ""),
            "character": name,
            "character_avatar": _character_avatar(name),
            "character_portrait": _character_portrait(name),
            "sect": sect or "?",
            "sect_icon": _sect_icon(sect),
            "sect_accent": _sect_accent(sect),
            # Sidejob / derivations aren't in the recent record; a matched
            # folder may fill them in (see list_games).
            "sidejob": "?",
            "sidejob_badge": None,
            "career_id": 0,
            "rounds_played": g.get("rounds_played", 0),
            "final_life": g.get("final_life"),
            "final_realm": None,
            "placement": g.get("placement"),
            "lost_rounds": g.get("lost_rounds", []),
            "derivations": [],
            "radar": g.get("radar"),         # per-category net-destiny buckets
            # has_detail gates the winnable 复盘 (needs the counter's exact
            # board recording — folder-only). can_view gates the per-round card
            # 查看, which we can build from the recent record's [103] cards.
            "has_detail": False,
            "can_view": True,
        })
    return out


def _recent_game_detail(game_id: str) -> dict | None:
    """Per-round 查看 detail for a recent (imported) game — built from the
    recentBattleDatas record's per-round cards. No exact board levels / hp /
    fates (the recent format doesn't carry them), but shows each round's cards,
    opponent, and win/loss."""
    try:
        import recent_battles
        me_name, me_char_id, _placement, rounds = recent_battles.game_rounds(game_id)
    except Exception as e:
        print(f"[game_archive] recent detail failed: {e}", flush=True)
        return None
    if not rounds:
        return None
    sect_map = _char_map().get("name_to_sect", {})
    me_char = _char_name_from_id(me_char_id) or "?"
    me_sect = sect_map.get(me_char, "?")

    def _board(cards):
        # Card level (1..3) comes from the id tier digit (see recent_battles);
        # dream/special cards carry None (no level badge).
        return [{"name": c["name"], "level": c.get("level")} for c in cards]

    rounds_out = []
    for i, rd in enumerate(rounds):
        life = rd["me_life"]
        if isinstance(life, int) and life <= 0:
            continue                      # phantom post-death round — don't show
        # A round is WON when net destiny (dealt - received) is >= 0. `net` (field [6])
        # is the game's own per-round result — verified bit-exact vs the Oracle's
        # lifeDamage. The old me_life-drop heuristic lagged (me_life is flat-then-stepped),
        # so it flagged the wrong rounds and missed round-1 losses entirely.
        net = rd.get("net")
        won = not (isinstance(net, int) and net < 0)
        opp_char = _char_name_from_id(rd["opp_char_id"]) or "?"
        opp_sect = sect_map.get(opp_char, "?")
        # Per-round stats decoded from the recent record: hp / xiuwei (修) /
        # tipo (体) / realm (境) / fates — for ME and the opponent.
        ms = rd.get("me_stats") or {}
        ops = rd.get("opp_stats") or {}
        rounds_out.append({
            "round": rd["round"],
            "won": won,
            "life_delta": None,
            "me": {
                "character": me_char,
                "character_avatar": _character_avatar(me_char),
                "sect": me_sect, "sect_icon": _sect_icon(me_sect),
                "life": ms.get("life", life), "max_hp": ms.get("max_hp"),
                "level": ms.get("realm"),
                "xiuwei": ms.get("xiuwei"), "tipo": ms.get("tipo"),
                "max_tipo": ms.get("max_tipo"),
                "board": _board(rd["me_cards"]),
                "fate_names": ms.get("fates") or [], "fates": [],
            },
            "opponent": {
                "username": rd["opp_name"] or "",
                "character": opp_char,
                "character_avatar": _character_avatar(opp_char),
                "sect": opp_sect, "sect_icon": _sect_icon(opp_sect),
                "life": ops.get("life"), "max_hp": ops.get("max_hp"),
                "level": ops.get("realm"),
                "xiuwei": ops.get("xiuwei"), "tipo": ops.get("tipo"),
                "max_tipo": ops.get("max_tipo"),
                "board": _board(rd["opp_cards"]),
                "fate_names": ops.get("fates") or [], "fates": [],
            },
        })
    return {"id": game_id, "me_name": me_name, "me_character": me_char,
            "rounds": rounds_out}


def build_recent_review_payload(game_id: str, rn: int) -> dict | None:
    """yisim_review.js payload for one round of an imported (recentBattleDatas)
    game. The recent record carries the exact board (real levels 1-3), hp / tipo
    / xiuwei / realm and fate ids — everything the sim needs. No `hand` is
    supplied (the recent deck list lacks per-card levels), so the winnable
    search permutes the played board rather than swapping in unplayed cards."""
    try:
        import recent_battles
        me_name, me_char_id, _pl, rounds = recent_battles.game_rounds(game_id)
    except Exception as e:
        print(f"[game_archive] recent review payload failed: {e}", flush=True)
        return None
    rd = next((r for r in rounds if r.get("round") == rn), None)
    if not rd:
        return None
    try:
        import proxy_view
        me_fates, me_fnames = proxy_view._fates_to_talents(
            (rd.get("me_stats") or {}).get("fate_ids") or [])
        opp_fates, opp_fnames = proxy_view._fates_to_talents(
            (rd.get("opp_stats") or {}).get("fate_ids") or [])
    except Exception:
        me_fates = me_fnames = opp_fates = opp_fnames = []

    def _side(char_id, stats, cards, fates, fnames):
        board = [{"name": c["name"], "level": c.get("level") or 1} for c in cards]
        return {
            "displayName": _char_name_from_id(char_id) or "",
            "deckSlots": stats.get("unlocked") or len(board) or 8,
            "hp": stats.get("max_hp"),
            "tipo": stats.get("tipo") or 0,
            "max_tipo": stats.get("max_tipo") or stats.get("tipo") or 0,
            "xiuwei": stats.get("xiuwei") or 0,
            "realm": stats.get("realm") or 1,
            "fates": fates, "fateNames": fnames,
            "slots": board,
        }
    return {
        "round": rn,
        "me": _side(me_char_id, rd.get("me_stats") or {},
                    rd["me_cards"], me_fates, me_fnames),
        "opponent": _side(rd.get("opp_char_id"), rd.get("opp_stats") or {},
                          rd["opp_cards"], opp_fates, opp_fnames),
    }


def _folder_epoch(folder_name: str) -> float | None:
    """battle_log folder name (local time) → epoch seconds, or None."""
    try:
        dt = datetime.datetime.strptime(folder_name, "%Y-%m-%d_%H%M%S")
        return dt.timestamp()
    except Exception:
        return None


def list_games() -> list[dict]:
    """Return every game we have a record for, summarized for the review UI.

    Primary source is the game's own recentBattleDatas (the user's authoritative
    history — far more complete than the counter's recordings, with the real
    final placement). Each recent game is matched (by start time, within 2 min)
    to a counter `battle_log/` folder when one exists, so the 查看 / 复盘 board
    detail keeps working for recorded games; recent-only games carry
    `has_detail=False` (the UI disables those buttons). Any folder with no
    recent match is still listed as a fallback.

    Sorted newest-first by timestamp.
    """
    _auto_convert_feeds()

    # Counter recordings, keyed by name, with an epoch for time-matching.
    folders: dict[str, dict] = {}
    if BATTLE_LOG.exists():
        for folder in BATTLE_LOG.iterdir():
            if not folder.is_dir():
                continue
            if not re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}$", folder.name):
                continue
            try:
                s = _folder_game_summary(folder)
                if s and s.get("rounds_played", 0) > 0:
                    s["_epoch"] = _folder_epoch(folder.name)
                    s["has_detail"] = True
                    folders[folder.name] = s
            except Exception as e:
                print(f"[game_archive] folder {folder.name} skipped: {e}",
                      flush=True)

    recent = _recent_game_summaries()
    out = []
    used = set()
    for g in recent:
        # Attach the counter folder for this game (gives board detail), matching
        # the recorded start time to the game's start within 2 minutes.
        gms = g.get("ts_ms")
        match = None
        if isinstance(gms, int):
            gsec = gms / 1000
            best = 121.0
            for fname, fs in folders.items():
                if fname in used or fs.get("_epoch") is None:
                    continue
                dd = abs(fs["_epoch"] - gsec)
                if dd < best:
                    best = dd
                    match = fname
        if match:
            used.add(match)
            fs = folders[match]
            g = dict(g)
            g["id"] = match                  # folder id → existing detail works
            g["format"] = "folder"
            g["has_detail"] = True
            # Borrow sidejob / derivations the recent record lacks.
            for k in ("sidejob", "sidejob_badge", "career_id", "derivations"):
                v = fs.get(k)
                if v not in (None, "?", 0, []):
                    g[k] = v
        out.append(g)

    # Folders with no recent match (older than the game's recent window) stay
    # listed so nothing the counter saved is lost.
    for fname, fs in folders.items():
        if fname not in used:
            fs.pop("_epoch", None)
            out.append(fs)

    out.sort(key=lambda g: g.get("ts", ""), reverse=True)
    return out


# ─── Per-round state extraction from deck_tracker.jsonl ───────────────────────
def extract_round_states(folder: Path) -> dict[int, dict]:
    """For each round, return the LAST view-model snapshot (final board/state)
    plus a UNION of every hand card the player held at any point during the
    round's prep — those are the alternate cards the player COULD have played
    instead of the ones that ended up on the board.

    Returns:
        {round_num: vm_dict} with an extra `me._all_hand_cards` field listing
        the union of hand cards ever held that round.
    """
    last_vm: dict[int, dict] = {}
    hand_union: dict[int, dict[str, dict]] = {}  # rn → key("name@lv") → card

    deck = folder / "deck_tracker.jsonl"
    if not deck.exists():
        return last_vm
    for line in deck.open("r", encoding="utf-8"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        vm = e.get("vm") or {}
        rn = vm.get("round")
        if not rn:
            continue
        last_vm[rn] = vm
        me_hand = ((vm.get("me") or {}).get("hand") or [])
        ru = hand_union.setdefault(rn, {})
        for c in me_hand:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            k = f"{c['name']}@{c.get('level', 1)}"
            ru[k] = c
    # Stitch the union back onto the last vm so callers can read it from one place.
    for rn, vm in last_vm.items():
        me = vm.get("me")
        if isinstance(me, dict):
            me["_all_hand_cards"] = list(hand_union.get(rn, {}).values())
    return last_vm


def build_review_payload(folder: Path, rn: int) -> dict | None:
    """Translate a deck_tracker view-model snapshot into the same shape
    yisim_review.js expects on stdin (round.me, round.opponent).

    Board source: `battle_log.json` per-player `usedCards`. The deck_tracker
    wire snapshot is captured at the START of the round (just after the
    previous round's GameStatus arrives) and reflects the player's
    PRE-PREP state. Players modify their boards during prep — only
    `BL.usedCards` reflects the actual battle-time arrangement (the cards
    that actually went into combat).

    Stats source: BL for hp/maxHp/level/tiPo/maxTiPo (authoritative
    end-of-prep values; battle-start hp = life - lifeDelta), deck_tracker
    vm for xiuwei/fates (only source for those).

    Returns None if BL records for the round are missing or empty.
    """
    states = extract_round_states(folder)
    vm = states.get(rn)
    if not vm:
        return None
    me_vm = vm.get("me") or {}
    opp_vm = vm.get("opponent") or {}

    bl_records = _read_bl_jsonl(folder / "battle_log.json")
    me_name = _resolve_me_name(folder, bl_records) or ""
    me_bl = None
    rec_players = []
    for rec in bl_records:
        if rec.get("round") != rn:
            continue
        rec_players = rec.get("players", [])
        me_bl = next((p for p in rec_players if p.get("username") == me_name), None)
        break
    if not me_bl or not me_bl.get("usedCards"):
        return None

    # Identify opponent by matching vm.opponent.board against each BL player's
    # usedCards. BL.opponentUsername is unreliable (often points to the NEXT
    # round's matchup peek, not the round we just fought). vm.opponent is the
    # authoritative current-round identity — pick the BL player whose
    # usedCards has the highest card-name overlap with vm.opponent.board.
    opp_board = opp_vm.get("board") or []
    opp_keys = set()
    for c in opp_board:
        if isinstance(c, dict) and c.get("name"):
            opp_keys.add(c["name"])
    opp_bl = None
    best_overlap = -1
    for p in rec_players:
        if p.get("username") == me_name:
            continue
        used = p.get("usedCards") or []
        if not used:
            continue
        used_keys = {c.get("name") for c in used
                     if isinstance(c, dict) and c.get("name")}
        overlap = len(opp_keys & used_keys)
        if overlap > best_overlap:
            best_overlap = overlap
            opp_bl = p
    if not opp_bl or best_overlap <= 0:
        return None

    def _slots_from_used_cards(used_cards):
        out = []
        for c in used_cards or []:
            if isinstance(c, dict) and c.get("name"):
                out.append({"name": c["name"], "level": c.get("level", 1)})
            else:
                out.append(None)
        return out

    def _side(p_vm, p_bl, include_hand=False):
        slots = _slots_from_used_cards(p_bl.get("usedCards"))
        # Each round starts battle hp = maxHp. The BL `life` field is the
        # elimination life pool (gets debited by battle damage between rounds).
        max_hp = p_bl.get("maxHp")
        # `exp` is end-of-round cultivation; winners get +2 round-end bonus,
        # so battle-time cult = exp - 2 for winners (lifeDelta == 0 in their
        # own player record), exp as-is for losers (lifeDelta < 0).
        end_exp = p_bl.get("exp") or 0
        won = (p_bl.get("lifeDelta") or 0) >= 0
        battle_exp = end_exp - 2 if won else end_exp
        side = {
            "displayName": p_bl.get("character") or p_vm.get("displayName", ""),
            "deckSlots": len(slots) or p_vm.get("unlocked", 8),
            "hp": max_hp,
            "tipo": p_bl.get("tiPo", 0) or 0,
            "max_tipo": p_bl.get("maxTiPo", 0) or 0,
            "xiuwei": battle_exp,
            "realm": p_bl.get("level", p_vm.get("realm_tier", 1)),
            "fates": p_vm.get("fates") or [],
            "fateNames": p_vm.get("fateNames") or [],
            "slots": slots,
        }
        if include_hand:
            alts = p_vm.get("_all_hand_cards") or p_vm.get("hand") or []
            board_keys = set()
            for c in slots:
                if isinstance(c, dict) and c.get("name"):
                    board_keys.add(f"{c['name']}@{c.get('level', 1)}")
            side["hand"] = [
                c for c in alts
                if isinstance(c, dict) and c.get("name")
                and f"{c['name']}@{c.get('level', 1)}" not in board_keys
            ]
        return side
    return {"round": rn, "me": _side(me_vm, me_bl, include_hand=True),
            "opponent": _side(opp_vm, opp_bl)}


def game_detail(game_id: str) -> dict | None:
    """Per-round detail for the 查看 view: ME and OPPONENT boards, fates,
    and who won each round. Folder-format only (per-round game files lack
    the round-by-round time series we need)."""
    folder = BATTLE_LOG / game_id
    if not folder.is_dir():
        # Not a counter recording — try the imported recentBattleDatas game.
        return _recent_game_detail(game_id)
    bl_records = _read_bl_jsonl(folder / "battle_log.json")
    msgdump = folder / "msgdump.jsonl"
    me_name = _resolve_me_name(folder, bl_records) or ""
    states = extract_round_states(folder)

    # Real card level (1..3) lives only in the game's own recentBattleDatas
    # record, not battle_log (whose `level` field is the card's PHASE). Graft
    # the matching recent game's leveled boards on by round so 查看 shows the
    # real level everywhere. Best-effort: {} if no recent match (keeps the
    # battle_log board as a fallback).
    recent_boards = {}
    epoch = _folder_epoch(folder.name)
    if epoch is not None:
        try:
            import recent_battles
            recent_boards = recent_battles.board_by_round_near(int(epoch * 1000))
        except Exception as e:
            print(f"[game_archive] recent board graft skipped: {e}", flush=True)

    # Find ME's elimination round so post-elimination spectator rounds are
    # excluded from the per-round detail view.
    me_recs = []
    for rec in bl_records:
        for p in rec.get("players", []):
            if p.get("username") == me_name:
                me_recs.append({
                    "round": rec.get("round"),
                    "life": p.get("life"),
                    "lifeDelta": p.get("lifeDelta"),
                    "opponentUsername": p.get("opponentUsername"),
                })
                break
    me_recs.sort(key=lambda r: r["round"] or 0)
    elim_round = _elimination_round(me_recs)

    rounds_out = []
    me_character_seen = ""
    for rec in bl_records:
        rn = rec.get("round")
        if not rn or rn not in states:
            continue
        if elim_round is not None and rn > elim_round:
            continue   # spectator round — drop
        vm = states[rn]
        me_vm = vm.get("me") or {}
        opp_vm = vm.get("opponent") or {}
        # Find ME's BL record for win/loss determination.
        me_bl = next((p for p in rec.get("players", [])
                      if p.get("username") == me_name), None) or {}
        opp_username = me_bl.get("opponentUsername", "")
        opp_bl = next((p for p in rec.get("players", [])
                       if p.get("username") == opp_username), None) or {}
        life_delta = me_bl.get("lifeDelta", 0) or 0
        won = life_delta >= 0
        if me_character_seen == "" and me_bl.get("character"):
            me_character_seen = me_bl.get("character")
        # Prefer the recent record's leveled board (real level 1..3); fall back
        # to the battle_log/deck_tracker board (phase as level) if unmatched.
        rb_round = recent_boards.get(rn) or {}
        me_board = rb_round.get("me") or me_vm.get("board") or []
        opp_board = rb_round.get("opp") or opp_vm.get("board") or []
        rounds_out.append({
            "round": rn,
            "won": won,
            "life_delta": life_delta,
            "me": {
                "character": me_character_seen or me_bl.get("character") or "?",
                "character_avatar": _character_avatar(
                    me_character_seen or me_bl.get("character") or ""),
                "sect": me_bl.get("sect") or "?",
                "sect_icon": _sect_icon(me_bl.get("sect") or ""),
                "life": me_bl.get("life"),
                "max_hp": me_bl.get("maxHp"),
                "level": me_bl.get("level"),
                "xiuwei": me_vm.get("xiuwei"),
                "tipo": me_vm.get("tipo"),
                "max_tipo": me_vm.get("max_tipo"),
                "board": me_board,
                "fate_names": me_vm.get("fateNames") or [],
                "fates": me_vm.get("fates") or [],
            },
            "opponent": {
                "username": opp_username,
                "character": opp_bl.get("character") or opp_vm.get("character") or "?",
                "character_avatar": _character_avatar(
                    opp_bl.get("character") or opp_vm.get("character") or ""),
                "sect": opp_bl.get("sect") or "?",
                "sect_icon": _sect_icon(opp_bl.get("sect") or ""),
                "life": opp_bl.get("life"),
                "max_hp": opp_bl.get("maxHp"),
                "level": opp_bl.get("level"),
                "xiuwei": opp_vm.get("xiuwei"),
                "tipo": opp_vm.get("tipo"),
                "max_tipo": opp_vm.get("max_tipo"),
                "board": opp_board,
                "fate_names": opp_vm.get("fateNames") or [],
                "fates": opp_vm.get("fates") or [],
            },
        })
    rounds_out.sort(key=lambda r: r["round"])
    return {
        "id": game_id,
        "me_name": me_name,
        "me_character": me_character_seen,
        "rounds": rounds_out,
    }


def load_game(game_id: str) -> dict | None:
    """Return the full per-round breakdown for a single game, ready for the
    review window to render (and for yisim re-simulation in Stage 2)."""
    folder = BATTLE_LOG / game_id
    if folder.is_dir():
        rounds = []
        bl_records = _read_bl_jsonl(folder / "battle_log.json")
        me_name = _resolve_me_name(folder, bl_records)
        for rec in bl_records:
            for p in rec.get("players", []):
                if p.get("username") == me_name:
                    rounds.append({
                        "round": rec.get("round"),
                        "life": p.get("life"),
                        "maxHp": p.get("maxHp"),
                        "level": p.get("level"),
                        "lifeDelta": p.get("lifeDelta"),
                        "won": (p.get("lifeDelta") or 0) >= 0,
                        "opponent": p.get("opponentUsername"),
                        "usedCards": p.get("usedCards", []),
                    })
                    break
        rounds.sort(key=lambda r: r["round"] or 0)
        # Drop post-elimination spectator rounds so review() doesn't try to
        # rerun yisim on rounds where the player wasn't actually playing.
        elim_round = _elimination_round(rounds)
        if elim_round is not None:
            rounds = [r for r in rounds if (r["round"] or 0) <= elim_round]
        return {"id": game_id, "format": "folder", "rounds": rounds}
    # Per-round format
    sessions = _per_round_games()
    if game_id in sessions:
        rs = sessions[game_id]
        out_rounds = []
        for r in rs:
            diff = r.get("br_pb5_hp_diff", 0)
            is_pb1 = r.get("br_pb1_is_me", False)
            me_won = (diff > 0) if is_pb1 else (diff < 0)
            out_rounds.append({
                "round": r.get("round") or r.get("_round"),
                "won": me_won,
                "hp_diff": diff,
                "me": r.get("me"),
                "opponent": r.get("opponent"),
            })
        return {"id": game_id, "format": "per_round", "rounds": out_rounds}
    # Imported recentBattleDatas game (id = start_local).
    try:
        import recent_battles
        _mn, _cid, _pl, rounds = recent_battles.game_rounds(game_id)
    except Exception:
        rounds = []
    if rounds:
        out_rounds = []
        for i, rd in enumerate(rounds):
            life = rd.get("me_life")
            if isinstance(life, int) and life <= 0:
                continue                  # phantom post-death round
            # WON when net destiny (dealt - received) >= 0. `net` (field [6]) is the
            # game's own per-round result — verified bit-exact vs the Oracle's lifeDamage.
            # (The old me_life-drop heuristic lagged: me_life is flat-then-stepped, so it
            # flagged the wrong rounds and missed round-1 losses entirely.)
            net = rd.get("net")
            won = not (isinstance(net, int) and net < 0)
            out_rounds.append({"round": rd["round"], "won": won})
        return {"id": game_id, "format": "recent", "rounds": out_rounds}
    return None
