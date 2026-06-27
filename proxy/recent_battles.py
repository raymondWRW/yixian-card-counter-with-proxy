"""
recent_battles.py — decode the game's own `recentBattleDatas/*.bin` replays.

The game client stores the user's recent games (server-downloaded battle
records) as protobuf under

  %LOCALAPPDATA%\\..\\LocalLow\\DarkSunStudio\\YiXianPai\\
      userLocalDatas\\<account>\\recentBattleDatas\\*.bin

This is a far more complete history than the counter ever recorded — the
counter only captures while it is running, whereas the game keeps ~200 recent
games regardless. Each file is one game from the USER's perspective: the
per-round matchups (me vs that round's opponent), characters, destiny-pool
life, and the authoritative final placement.

Wire field map (reverse-engineered; verified against games whose placement we
already knew — e.g. the user-confirmed 2nd-place 炎雪 run):

  top-level (the game)
    [1]  battle id (24-hex str)      [2]  game mode (3 = ranked 8-player)
    [4]  start ms                    [5]  end ms
    [6]  my character id             [8]  placement - 1   (0 omitted ⇒ 1st)
    [15] final destiny-pool life     [18] my account id
    [26] round count

The folder mixes two modes: [2]==3 is the real ranked 8-player game (13–21
rounds, the kind the counter recorded); [2]==2 is a casual/abandoned mode
(1–11 rounds, almost always logged as last place). Only ranked games are
returned — the casual ones aren't what the review is for.
  each round entry in repeated [100]
    [1] = opponent  {1:{core}}       [2] = me  {1:{core}}
    core[1]=player id  core[2]=name  core[3]=destiny life (round start)
    core[12]=character id
    round-scalar [4] = round number

Only what the review's game LIST needs is decoded here (date, character,
placement, rounds, win/loss). Per-round BOARDS are encoded in a packed binary
form that isn't mapped yet — see the importer notes; `game_detail` / the
"winnable?" review still rely on the counter's `battle_log/` folders.
"""
from __future__ import annotations

import datetime
import glob
import os
from pathlib import Path


# ─── Minimal protobuf wire reader ─────────────────────────────────────────────
# Hand-rolled (not blackboxprotobuf) because that library hangs on some of these
# files; we only need a fast top-level + shallow-nested scan anyway.
def _read_varint(b: bytes, i: int):
    shift = 0
    out = 0
    while True:
        x = b[i]
        i += 1
        out |= (x & 0x7F) << shift
        if not (x & 0x80):
            return out, i
        shift += 7


def _parse(b: bytes, i: int = 0, end: int | None = None) -> dict:
    """Parse one protobuf message → {field_num: [values]}. LEN payloads stay
    as raw bytes (decode further with _parse only when you need to)."""
    if end is None:
        end = len(b)
    out: dict[int, list] = {}
    while i < end:
        try:
            tag, i = _read_varint(b, i)
        except IndexError:
            break
        fn, wt = tag >> 3, tag & 7
        if wt == 0:
            v, i = _read_varint(b, i)
        elif wt == 2:
            ln, i = _read_varint(b, i)
            v = b[i:i + ln]
            i += ln
        elif wt == 1:
            v = b[i:i + 8]
            i += 8
        elif wt == 5:
            v = b[i:i + 4]
            i += 4
        else:
            break
        out.setdefault(fn, []).append(v)
    return out


def _first(d: dict, fn: int):
    v = d.get(fn)
    return v[0] if v else None


def _s(x):
    if isinstance(x, (bytes, bytearray)):
        try:
            return bytes(x).decode("utf-8")
        except Exception:
            return None
    return x


def _signed(v):
    """protobuf varints store negative int64s as their unsigned 2's-complement;
    a destiny pool drained below 0 shows up as a huge value. Fold it back."""
    if isinstance(v, int) and v >= (1 << 63):
        return v - (1 << 64)
    return v


# Realm tier (境) → base max-HP. Real HP = this base + the recorded extra-HP
# (core[4]); verified exact against battle_log maxHp. Mirrors proxy_view's table.
_REALM_BASE_HP = {1: 40, 2: 45, 3: 52, 4: 62, 5: 75}

# Game mode [2]==3 is the ranked 8-player game; [2]==2 is casual/abandoned.
RANKED_MODE = 3
# Real ranked games never finish before ~round 13; below this is an aborted
# capture, not a game worth reviewing (same floor game_archive uses).
MIN_ROUNDS = 5


# ─── Locate the recentBattleDatas directory ───────────────────────────────────
def _recent_dirs() -> list[Path]:
    """Every `userLocalDatas/<account>/recentBattleDatas` dir on this machine
    (normally one). Each account folder name is that account's id."""
    root = Path(os.path.expandvars(
        r"%LOCALAPPDATA%\..\LocalLow\DarkSunStudio\YiXianPai\userLocalDatas"))
    if not root.exists():
        return []
    out = []
    for acct in root.iterdir():
        d = acct / "recentBattleDatas"
        if d.is_dir():
            out.append(d)
    return out


# ─── Card-id → name map (proxy/card_id_map.json) ──────────────────────────────
_card_map_cache = None


def _card_name(cid) -> str | None:
    """Card id → display name. The map carries the same name at several ids
    (base / leveled variants); any of them resolves to the card's name."""
    global _card_map_cache
    if _card_map_cache is None:
        try:
            import json
            p = Path(__file__).resolve().parent / "card_id_map.json"
            _card_map_cache = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            _card_map_cache = {}
    return _card_map_cache.get(str(cid))


_fate_map_cache = None


def _fate_name(fid):
    """Fate id → display name (proxy/fate_id_map.json)."""
    global _fate_map_cache
    if _fate_map_cache is None:
        try:
            import json
            p = Path(__file__).resolve().parent / "fate_id_map.json"
            _fate_map_cache = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            _fate_map_cache = {}
    return _fate_map_cache.get(str(fid))


def _player_core(slot_msg) -> dict:
    """A round's player slot is {1:{core}, 2:{...}}; return the parsed core."""
    return _parse(_first(_parse(slot_msg), 1) or b"")


# Stat ids inside the player's stat-counter list (core[17] = repeated
# {1: stat_id, 2: count}). tipo lives here keyed by id, not at a fixed field.
_STAT_TIPO = 10023      # 体魄 (physique) — verified exact vs battle_log tiPo
_STAT_MAX_TIPO = 10024  # 体魄上限 (max physique)


def _stat(core: dict, stat_id: int):
    """Look up a stat counter's value by id in core[17]'s {stat_id, count} list."""
    for e in core.get(17, []):
        em = _parse(e)
        if _first(em, 1) == stat_id:
            return _first(em, 2)
    return None


def _player_stats(core: dict) -> dict:
    """Per-round stats from a player's core. The core[200] container mirrors the
    live GameStatus layout (see proxy_analysis/hp_field_chart*.md):

      core[3]      destiny pool (命元)
      core[17]     stat-counter list {id, count} — 体魄 is id 10023, max 10024
      core[200].2  extra max-HP (over the realm base; includes max-HP cards)
      core[200].3  cultivation 修为 (xiuwei)   core[200].4  realm tier (境)
      core[200].5  owned fate ids (packed varint list)

    HP is the realm base (_REALM_BASE_HP) + the recorded extra-HP — verified
    exact against battle_log maxHp for both a 修为 and a 体魄 game. 体魄 (tipo)
    is 0/absent for most characters and only nonzero for physique builds
    (小布, 姬方生, …) — verified exact vs battle_log tiPo.
    """
    p200 = _parse(_first(core, 200) or b"")
    realm = _first(p200, 4)
    base_hp = _REALM_BASE_HP.get(realm) if isinstance(realm, int) else None
    extra_hp = _first(p200, 2) or 0
    fate_ids = []
    f5 = _first(p200, 5)
    if isinstance(f5, (bytes, bytearray)):
        fate_ids = _packed_varints(bytes(f5))
    return {
        "life": _signed(_first(core, 3)),
        "realm": realm,
        "xiuwei": _first(p200, 3),
        "tipo": _stat(core, _STAT_TIPO) or 0,
        "max_tipo": _stat(core, _STAT_MAX_TIPO),
        "max_hp": (base_hp + extra_hp) if base_hp is not None else None,
        "unlocked": _first(p200, 10),       # unlocked board slots
        "fate_ids": fate_ids,
        "fates": [_fate_name(fid) or str(fid) for fid in fate_ids],
    }


def _packed_varints(b: bytes) -> list[int]:
    """Decode a blob of back-to-back varints (no field tags) into ints."""
    out = []
    i, n = 0, len(b)
    while i < n:
        shift = 0
        val = 0
        while i < n:
            x = b[i]
            i += 1
            val |= (x & 0x7F) << shift
            if not (x & 0x80):
                break
            shift += 7
        out.append(val)
    return out


def _card_level(cid: int):
    """Card play-level (1..3) from the id's 10,000s digit. A card's three id
    variants (e.g. 1000042 / 1010042 / 1020042) are levels 1/2/3 — the digit
    that increases as copies are merged. 梦 ("dream") and other special cards
    sit above tier 2 (digit ≥3) and have no normal level → None."""
    lv = (cid // 10000) % 10 + 1
    return lv if 1 <= lv <= 3 else None


def _core_cards(core: dict) -> list[dict]:
    """A player's actual battle BOARD — the 8-slot arrangement, with duplicates
    — is packed into core[200][6] as back-to-back varint card ids, one per
    slot. Verified exact against battle_log usedCards (names + order + dupes).

    Returns [{name, id, level}] in slot order. Level comes from the id's tier
    digit (see _card_level). (battle_log's `level` field is actually the card's
    PHASE, 1..5 — a different thing; the real merge level is 1..3.)
    """
    p200 = _parse(_first(core, 200) or b"")
    blob = _first(p200, 6)
    if not isinstance(blob, (bytes, bytearray)):
        return []
    out = []
    for cid in _packed_varints(bytes(blob)):
        nm = _card_name(cid)
        if nm:
            out.append({"name": nm, "id": cid, "level": _card_level(cid)})
    return out


# ─── Decode one battle file ───────────────────────────────────────────────────
def _decode_rounds(top: dict, account_id: str):
    """Walk the repeated [100] round entries. Returns (me_name, rounds) where
    rounds is sorted by round number ([7]) and each item is:
      {round, me_life, me_cards, opp_name, opp_char_id, opp_cards}.
    me_life is my destiny pool at the start of that round."""
    me_name = None
    rounds = []
    for rb in top.get(100, []):
        r = _parse(rb)
        rn = _first(r, 7)                     # [7] is the round number (1..N)
        me = opp = None
        me_slot = None
        for slot in (1, 2):
            pm = _first(r, slot)
            if not pm:
                continue
            core = _player_core(pm)
            if _s(_first(core, 1)) == account_id:
                me = core
                me_slot = slot
            else:
                opp = core
        if me is None:
            continue
        me_name = _s(_first(me, 2)) or me_name
        # Round-level [6] is the destiny delta from slot-1's perspective, so the
        # net destiny I dealt minus received = [6] when I'm slot 1, else -[6].
        # Verified exact vs battle_log (oppΔ - myΔ). Slot also encodes turn
        # order: slot 1 went first (先手), slot 2 second (后手).
        r6 = _signed(_first(r, 6))
        net = None
        if isinstance(r6, int):
            net = r6 if me_slot == 1 else -r6
        rounds.append({
            "round": rn,
            "slot": me_slot,
            "net": net,
            "me_life": _signed(_first(me, 3)),
            "me_cards": _core_cards(me),
            "me_stats": _player_stats(me),
            "opp_name": _s(_first(opp, 2)) if opp else None,
            "opp_char_id": _first(opp, 12) if opp else None,
            "opp_cards": _core_cards(opp) if opp else [],
            "opp_stats": _player_stats(opp) if opp else {},
        })
    rounds.sort(key=lambda x: x["round"] if isinstance(x["round"], int) else 1 << 30)
    return me_name, rounds


def _decode_file(path: Path, account_id: str) -> dict | None:
    """Decode one `.bin` into a raw game summary, or None if it isn't one of the
    local user's ranked games (account_id must appear as a player)."""
    try:
        top = _parse(path.read_bytes())
    except Exception:
        return None

    # Only ranked 8-player games — skip the casual/abandoned mode.
    if _first(top, 2) != RANKED_MODE:
        return None
    start_ms = _first(top, 4)
    if not isinstance(start_ms, int):
        return None
    rounds_count = _first(top, 26)
    if not isinstance(rounds_count, int) or rounds_count < MIN_ROUNDS:
        return None

    me_name, rounds = _decode_rounds(top, account_id)
    if not me_name:
        return None

    # me_life is my destiny pool at the START of each round. I LOST a round if
    # the pool dropped going into the next round (the elimination round shows up
    # as a drop into a NEGATIVE next value). The record appends a phantom round
    # AFTER death (start life <= 0); those aren't rounds I played, so they're
    # excluded from the count and win/loss. (top[15] looked like final life but
    # isn't reliable, so we read the trajectory directly.)
    lost_rounds: list[int] = []
    real_rounds = 0
    for idx, rd in enumerate(rounds):
        life = rd["me_life"]
        if isinstance(life, int) and life <= 0:
            continue                      # phantom post-death round
        real_rounds += 1
        # A round is LOST when net destiny (dealt - received) is negative. `net` is the
        # game's own per-round result (verified bit-exact vs the Oracle's lifeDamage).
        # The old me_life-drop heuristic lagged — me_life is flat-then-stepped, so it
        # flagged the wrong rounds and missed round-1 losses entirely.
        net = rd.get("net")
        if isinstance(net, int) and net < 0:
            lost_rounds.append(rd["round"])
    opponents = sorted({rd["opp_name"] for rd in rounds if rd["opp_name"]})

    # Radar buckets: net destiny (dealt - received) summed per category, with a
    # round count, so the caller can take a recency-weighted average. Phantom
    # post-death rounds (me_life <= 0) are excluded.
    radar = {k: {"s": 0.0, "n": 0}
             for k in ("early", "mid", "late", "first", "second")}
    for rd in rounds:
        life = rd["me_life"]
        if isinstance(life, int) and life <= 0:
            continue
        net = rd.get("net")
        if not isinstance(net, (int, float)):
            continue
        rn = rd["round"]
        if isinstance(rn, int):
            cat = "early" if rn <= 7 else "mid" if rn <= 13 else "late"
            radar[cat]["s"] += net
            radar[cat]["n"] += 1
        slot = rd.get("slot")
        if slot == 1:
            radar["first"]["s"] += net
            radar["first"]["n"] += 1
        elif slot == 2:
            radar["second"]["s"] += net
            radar["second"]["n"] += 1

    start_dt = datetime.datetime.fromtimestamp(start_ms / 1000)
    return {
        "battle_id": _s(_first(top, 1)),
        "ts_ms": start_ms,
        # Local-time id in the same YYYY-MM-DD_HHMMSS shape battle_log folders
        # use, so the review's fmtTs renders it and folders can be matched.
        "start_local": start_dt.strftime("%Y-%m-%d_%H%M%S"),
        "minute_key": start_dt.strftime("%Y-%m-%d_%H%M"),
        "me_name": me_name,
        "character_id": _first(top, 6),
        "rounds_played": real_rounds or rounds_count,
        "placement": (_first(top, 8) or 0) + 1,   # [8] is placement-1; 1st omits
        "final_life": max(0, _signed(_first(top, 15) or 0)),
        "lost_rounds": lost_rounds,
        "opponents": opponents,
        "radar": radar,
    }


def decode_recent_games() -> list[dict]:
    """Decode every local recentBattleDatas file that is one of the user's own
    ranked games. Returns raw summaries (no avatar/sect enrichment — the caller
    does that), newest-first by start time."""
    out = []
    for d in _recent_dirs():
        account_id = d.parent.name
        for f in d.glob("*.bin"):
            g = _decode_file(f, account_id)
            if g:
                out.append(g)
    out.sort(key=lambda g: g["ts_ms"], reverse=True)
    return out


def game_rounds(start_local: str):
    """Per-round detail for one recent game, identified by its start_local id
    (YYYY-MM-DD_HHMMSS). Returns (me_name, me_char_id, placement, rounds) or
    (None, None, None, []) if not found. Used by the 查看 detail view."""
    for d in _recent_dirs():
        account_id = d.parent.name
        for f in d.glob("*.bin"):
            try:
                top = _parse(f.read_bytes())
            except Exception:
                continue
            if _first(top, 2) != RANKED_MODE:
                continue
            ms = _first(top, 4)
            if not isinstance(ms, int):
                continue
            if datetime.datetime.fromtimestamp(ms / 1000).strftime(
                    "%Y-%m-%d_%H%M%S") != start_local:
                continue
            me_name, rounds = _decode_rounds(top, account_id)
            if not me_name:
                return None, None, None, []
            return (me_name, _first(top, 6),
                    (_first(top, 8) or 0) + 1, rounds)
    return None, None, None, []


def round_stat_b64(start_local: str, rn: int):
    """Raw bytes of one round's RecentBattleInfo roundStat (field [100] element whose
    [7]==rn), base64-encoded, for priming the Yi Xian Oracle. Returns
    (me_side, b64) or (None, None), where me_side is "p1"/"p2" matching the Oracle's
    p1=slot1 / p2=slot2 (verified) — derived from the account UID, so it's correct
    even in mirror matches (both fighters the same character). The roundStat is
    exactly what the Oracle's RecentBattleInfo.roundStats element deserializes."""
    import base64
    for d in _recent_dirs():
        account_id = d.parent.name
        for f in d.glob("*.bin"):
            try:
                top = _parse(f.read_bytes())
            except Exception:
                continue
            if _first(top, 2) != RANKED_MODE:
                continue
            ms = _first(top, 4)
            if not isinstance(ms, int):
                continue
            if datetime.datetime.fromtimestamp(ms / 1000).strftime(
                    "%Y-%m-%d_%H%M%S") != start_local:
                continue
            for rb in top.get(100, []):
                rb = bytes(rb)
                r = _parse(rb)
                if _first(r, 7) != rn:
                    continue
                me_side = None
                for slot in (1, 2):
                    pm = _first(r, slot)
                    if pm and _s(_first(_player_core(pm), 1)) == account_id:
                        me_side = "p1" if slot == 1 else "p2"
                return me_side, base64.b64encode(rb).decode("ascii")
            return None, None
    return None, None


def board_by_round_near(ts_ms: int, tol_sec: int = 150):
    """Find the recent game whose start time is within tol_sec of ts_ms and
    return {round_number: {"me": [{name, level}], "opp": [{name, level}]}}.

    Used to graft the recent record's leveled boards onto a counter-recorded
    (battle_log folder) game, so the 查看 view shows the real card level (1..3)
    everywhere instead of battle_log's phase field. Returns {} if no game is
    close enough."""
    best = None
    best_diff = tol_sec * 1000 + 1
    for d in _recent_dirs():
        account_id = d.parent.name
        for f in d.glob("*.bin"):
            try:
                top = _parse(f.read_bytes())
            except Exception:
                continue
            if _first(top, 2) != RANKED_MODE:
                continue
            ms = _first(top, 4)
            if not isinstance(ms, int):
                continue
            diff = abs(ms - ts_ms)
            if diff < best_diff:
                best_diff = diff
                best = (top, account_id)
    if not best:
        return {}
    top, account_id = best
    _me, rounds = _decode_rounds(top, account_id)
    out = {}
    for rd in rounds:
        rn = rd["round"]
        if not isinstance(rn, int):
            continue
        out[rn] = {
            "me": [{"name": c["name"], "level": c["level"]} for c in rd["me_cards"]],
            "opp": [{"name": c["name"], "level": c["level"]} for c in rd["opp_cards"]],
        }
    return out
