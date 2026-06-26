# -*- coding: utf-8 -*-
"""oracle_sim.py — damage/what-if via the Yi Xian Oracle (the game's OWN combat code,
run headless), replacing the yisim JS reimplementation.

The Oracle runs as a warm `--serve` subprocess (oracle/scripts/oracle_pool.py). We talk to
it in JSON lines. For the 复盘 (review) what-if we:

  1. prime  — cache a recorded round's stat (raw RecentBattleInfo roundStat bytes) under an id
  2. describe— read each side's {characterId, usedCards(=played board)} to pick which side is "me"
  3. boards — evaluate many board arrangements (usedCards overrides) on that round in ONE call,
              each returning [hpDelta, turns]; hpDelta = p1.hp - p2.hp.

Bit-exact for the recorded board (verified), and reuses the round's real RNG/talents/buffs — we
only swap which cards "me" played. A winning arrangement is one where my side's hp advantage flips
positive.

If the Oracle isn't built/available, `available()` returns False so callers can fall back to yisim.
"""
import os
import sys
import base64
import itertools
import random
from pathlib import Path

_BASE = Path(__file__).resolve().parent           # proxy/
_REPO = _BASE.parent
_ORACLE_SCRIPTS = _REPO / "oracle" / "scripts"
_ORACLE_EXE = _REPO / "oracle" / "Oracle" / "bin" / "Release" / "net8.0" / "Oracle.exe"

# ── card id → {name, level} (for rendering winning_slots the UI understands) ──────────────────
_card_map = None


def _card_name(cid: int):
    global _card_map
    if _card_map is None:
        import json
        try:
            _card_map = json.loads((_BASE / "card_id_map.json").read_text(encoding="utf-8"))
        except Exception:
            _card_map = {}
    return _card_map.get(str(cid))


def _card_level(cid: int) -> int:
    # tier digit: (cid//10000)%10 + 1 → 1..3 for real cards (matches recent_battles / yisim clamp)
    try:
        return (int(cid) // 10000) % 10 + 1
    except Exception:
        return 1


def _slot(cid):
    if not cid:
        return None
    nm = _card_name(cid)
    return {"name": nm, "level": _card_level(cid)} if nm else None


# ── warm worker (lazy singleton) ──────────────────────────────────────────────────────────────
# The worker is ONE subprocess with a single stdin/stdout pipe — NOT thread-safe. The live UI fires
# matchups on every board change, and pywebview dispatches those api calls on multiple threads, so
# without this lock two calls interleave on the pipe, desync it, and run() blocks forever (frozen
# damage panel). Every worker interaction must hold _lock; multi-step sequences (prime→describe→
# boards) must hold it for the WHOLE sequence so a concurrent call can't corrupt mid-stream.
import threading
_worker = None
_worker_failed = False
_lock = threading.RLock()


def _get_worker():
    global _worker, _worker_failed
    if _worker is not None:
        return _worker
    if _worker_failed or not _ORACLE_EXE.exists():
        _worker_failed = True
        return None
    # Lock the spawn too, so a warmup thread and a matchup call can't create two
    # workers. (_lock is reentrant: callers that already hold it re-enter fine.)
    with _lock:
        if _worker is not None:
            return _worker
        try:
            if str(_ORACLE_SCRIPTS) not in sys.path:
                sys.path.insert(0, str(_ORACLE_SCRIPTS))
            from oracle_pool import OracleWorker
            _worker = OracleWorker()
            return _worker
        except Exception as e:
            print(f"[oracle] worker unavailable ({e}); falling back to yisim", flush=True)
            _worker_failed = True
            return None


def warmup():
    """Spawn the Oracle worker in the background so the first live matchup is instant
    (the ~3.4s DLL-load + config cold-start is paid here, off the UI path). No-op if
    the Oracle isn't built. Safe to call once at app startup."""
    if _worker is not None or _worker_failed or not _ORACLE_EXE.exists():
        return

    def _go():
        try:
            t0 = __import__("time").time()
            if _get_worker() is not None:
                print(f"[oracle] worker warmed in {__import__('time').time()-t0:.1f}s", flush=True)
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True, name="oracle-warmup").start()


def _reset_worker():
    """Tear down a broken/desynced worker so the next call respawns a fresh one."""
    global _worker
    w, _worker = _worker, None
    if w is not None:
        try:
            w.proc.kill()
        except Exception:
            pass


def available() -> bool:
    """True if the Oracle engine is built and a worker can be reached."""
    return _get_worker() is not None


def shutdown():
    global _worker
    if _worker is not None:
        try:
            _worker.close()
        except Exception:
            pass
        _worker = None


# ── candidate board generation (mirrors tools/yisim_review.js search) ──────────────────────────
def _candidates(board: list[int], pool: list[int], deck_slots: int, max_boards: int):
    """Yield up to max_boards distinct board arrangements (lists of card ids) to evaluate.
    Phase A: permutations of the played board. Phase B: single swaps with pool cards.
    Phase C: random deck_slots-sized subsets of the full pool."""
    seen = set()

    def emit(b):
        key = tuple(b)
        if key in seen:
            return None
        seen.add(key)
        return list(b)

    base = [c for c in board if c]
    # A — permutations of the played board (full perms if small, else random shuffles)
    if len(base) <= 6:
        for p in itertools.permutations(base):
            b = emit(list(p))
            if b is not None:
                yield b
            if len(seen) >= max_boards:
                return
    else:
        for _ in range(min(max_boards, 200)):
            s = base[:]
            random.shuffle(s)
            b = emit(s)
            if b is not None:
                yield b
            if len(seen) >= max_boards:
                return
    # B — replace one played card with one pool card
    extra = [c for c in pool if c and c not in base]
    for i in range(len(base)):
        for hc in extra:
            s = base[:]
            s[i] = hc
            b = emit(s)
            if b is not None:
                yield b
            if len(seen) >= max_boards:
                return
    # C — random subsets of the full pool, padded/truncated to deck_slots
    full = base + extra
    if full:
        for _ in range(max_boards - len(seen)):
            random.shuffle(full)
            b = emit(full[:max(1, min(deck_slots, len(full)))])
            if b is not None:
                yield b
            if len(seen) >= max_boards:
                return


def _player(side: dict) -> dict:
    """Normalize a live-state side dict to the Oracle's NativeFixturePlayer fields.
    Required: characterId, usedCards(board ids). Optional but damage-relevant: level(realm 1..5),
    extraMaxHp, talents(ids), fateStrategies(ids), sect, career, life, unlockGrids."""
    return {
        "characterId": side.get("characterId", 0),
        "level": side.get("level", 0),
        "sect": side.get("sect", 0),
        "career": side.get("career", 0),
        "life": side.get("life", 100),
        "extraMaxHp": side.get("extraMaxHp", 0),
        "unlockGrids": side.get("unlockGrids", 8),
        "usedCards": list(side.get("usedCards", [])),
        "talents": list(side.get("talents", [])),
        "fateStrategies": list(side.get("fateStrategies", [])),
    }


def matchup(me: dict, opp: dict, marginal: bool = False, rnd: int = 8):
    """Live matchup of MY board vs the OPPONENT's board, via the game's own engine (from-scratch
    fixture, no recorded RNG → a real single-sample outcome, not bit-exact but real game logic).
    me/opp carry the per-side live state (see _player). Returns:
      {win, hpDelta(p1-p2; +=me ahead), turns, lifeDamage(+ = I deal destiny), [marginal:{slot: dmg}]}
    marginal[i] = hpDelta(full) - hpDelta(without my card i) — each card's contribution.
    Returns None if the Oracle isn't available."""
    mp, op = _player(me), _player(opp)
    with _lock:
        w = _get_worker()
        if w is None:
            return None

        def run(cards):
            fx = {"p1": {**mp, "usedCards": list(cards)}, "p2": op,
                  "battleParams": [], "mainViewId": "", "round": rnd, "expected": {}}
            return w.run(fx)

        try:
            base = run(mp["usedCards"])
            out = {
                "win": base.get("hpDelta", 0) > 0,
                "hpDelta": base.get("hpDelta", 0),
                "turns": base.get("turns", 0),
                "lifeDamage": base.get("lifeDamage", 0),
            }
            if marginal:
                marg = {}
                full = base.get("hpDelta", 0)
                for i in range(len(mp["usedCards"])):
                    cards = mp["usedCards"][:i] + mp["usedCards"][i + 1:]
                    marg[i] = full - run(cards).get("hpDelta", 0)
                out["marginal"] = marg
            return out
        except Exception as e:
            _reset_worker()
            return {"error": f"matchup failed: {e}"}


def whatif_from_stat(stat_b64: str, my_side: str, pool_ids=None,
                     deck_slots: int = 8, max_boards: int = 400, slot_id: str = "rv"):
    """Thread-safe wrapper: the prime→describe→boards sequence must hold the worker
    lock for its whole duration (a concurrent matchup() would corrupt the pipe)."""
    with _lock:
        try:
            return _whatif_from_stat_impl(stat_b64, my_side, pool_ids, deck_slots, max_boards, slot_id)
        except Exception as e:
            _reset_worker()
            return {"error": f"whatif failed: {e}"}


def _whatif_from_stat_impl(stat_b64: str, my_side: str, pool_ids=None,
                           deck_slots: int = 8, max_boards: int = 400, slot_id: str = "rv"):
    """Search board arrangements for a recorded round; return a yisim_review-shaped result.

    stat_b64    base64 of the round's RecentBattleInfo roundStat proto bytes
    my_side     "p1" or "p2" — which fighter is me (slot-derived, mirror-safe). Defaults p1.
    pool_ids    extra card ids I could have played (hand); board cards are always included
    Returns {win, winning_slots, tried, original_hpDelta, my_side, ...} or {error}/None.
    hpDelta is p1.hp - p2.hp; my advantage = +hpDelta if I'm p1, else -hpDelta.
    """
    w = _get_worker()
    if w is None:
        return None
    ack = w.run({"prime": True, "id": slot_id, "statB64": stat_b64})
    if not ack.get("primed"):
        return {"error": "prime failed: " + str(ack.get("error"))}
    desc = w.run({"describe": True, "id": slot_id})
    rnd = desc.get("round", 0)
    my_side = "p2" if my_side == "p2" else "p1"
    sign = 1 if my_side == "p1" else -1
    board = desc.get(my_side, {}).get("usedCards", []) or []
    if not board:
        return {"error": "no board for my side"}

    # Outcome metric = destiny (命) damage from MY perspective. A round is WON when I defeat the
    # opponent's board (their hp -> 0) and deal them life damage; a draw (both survive the turn cap)
    # deals 0. Each board result is [hpDelta(p1-p2), turns, lifeDamage(+ = p1 deals / p2 loses life)].
    # my_life = +lifeDamage if I'm p1, else -lifeDamage. >0 = I win the round; <0 = I lose life.
    base = w.run({"id": slot_id, "round": rnd, "side": my_side, "boards": [board]})["results"][0]
    orig_life = sign * base[2]
    orig_hp = sign * base[0]

    # The game's own engine says I already won (or drew) this matchup — the played board dealt
    # life damage (orig_life > 0) or nobody died (==0). Not a loss to "fix"; report as-is. (Our
    # me_life-drop round flag can disagree with the engine's per-matchup result; the engine wins.)
    if orig_life >= 0:
        return {"win": False, "already_won": True, "tried": 1,
                "original_life": orig_life, "original_hpDelta": orig_hp, "my_side": my_side}

    cands = list(_candidates(board, list(board) + list(pool_ids or []), deck_slots, max_boards))
    if not cands:
        return {"win": False, "tried": 1, "original_life": orig_life,
                "original_hpDelta": orig_hp, "my_side": my_side}
    results = w.run({"id": slot_id, "round": rnd, "side": my_side, "boards": cands}).get("results", [])

    win_i, best_i, best_life, best_hp = -1, -1, orig_life, orig_hp
    for i, r in enumerate(results):
        my_life, my_hp = sign * r[2], sign * r[0]
        if win_i < 0 and my_life > 0 and tuple(cands[i]) != tuple(board):
            win_i = i
        # rank by (life won, then board margin) so "closest" is the most-promising near-miss
        if (my_life, my_hp) > (best_life, best_hp):
            best_life, best_hp, best_i = my_life, my_hp, i
    tried = 1 + len(cands)
    if win_i >= 0:
        wb = cands[win_i]
        return {
            "win": True, "outcome": "win", "tried": tried,
            "original_life": orig_life, "original_hpDelta": orig_hp,
            "winning_slots": [_slot(c) for c in wb],
            "end_turn": results[win_i][1],
            "my_side": my_side,
            "used_hand": any(c not in board for c in wb),
        }
    return {
        "win": False, "tried": tried,
        "original_life": orig_life, "original_hpDelta": orig_hp,
        "closest_life": best_life, "closest_hpDelta": best_hp,
        "my_side": my_side,
    }
