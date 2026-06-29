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


def _oracle_exe() -> Path:
    """Path to Oracle.exe: ORACLE_EXE env (set by oracle_bootstrap — the bundled
    self-contained exe when frozen) wins; else the dev build under oracle/."""
    return Path(os.environ.get("ORACLE_EXE")
                or (_REPO / "oracle" / "Oracle" / "bin" / "Release" / "net8.0" / "Oracle.exe"))

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


def _level_of(cid: int) -> int:
    """Card level via the canonical %100 formula (matches shadow_state._level_from_id /
    game_state.level_from_card_id). Used for opponent-pool base-copy counting."""
    try:
        cid = int(cid or 0)
        return ((cid // 10000) % 100) + 1 if cid > 0 else 1
    except Exception:
        return 1


def _line_of(cid: int) -> int:
    """The card LINE: its level-1 base id (strip the level digits). Two cards share
    a line iff they're the same card at different levels."""
    try:
        cid = int(cid or 0)
        return cid - ((cid // 10000) % 100) * 10000
    except Exception:
        return int(cid or 0)


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
    if _worker_failed or not _oracle_exe().exists():
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
            print(f"[oracle] worker unavailable ({e}); Oracle unavailable", flush=True)
            _worker_failed = True
            return None


def warmup():
    """Spawn the Oracle worker in the background so the first live matchup is instant
    (the ~3.4s DLL-load + config cold-start is paid here, off the UI path). No-op if
    the Oracle isn't built. Safe to call once at app startup."""
    if _worker is not None or _worker_failed or not _oracle_exe().exists():
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
    Budget is split across phases so each gets coverage (full permutations alone would
    otherwise starve the rest):
      A  permutations of the played board
      A2 FEWER cards / MORE empty slots (逍遥无影拳 et al. scale with empties)
      B  single swaps with a hand/pool card
      C  random deck-sized subsets of the full pool
    """
    seen = set()
    base = [c for c in board if c]
    extra = [c for c in pool if c and c not in base]

    def emit(b):
        key = tuple(b)
        if key in seen or not b:
            return None
        seen.add(key)
        return list(b)

    def run(gen, cap):
        """Drain `gen` until `cap` NEW boards are emitted or the global budget is hit.

        `_perms`/`_subsets` are INFINITE generators (while True / while full); when
        the distinct candidate space is smaller than `cap` they stop producing NEW
        boards but never end. Without the stall guard `run` would spin forever (hit
        with small live boards — a big pool in the review path masked it). Bail once
        we've seen many consecutive duplicates: the space is exhausted."""
        n = 0
        stall = 0
        STALL_LIMIT = 2000
        for cand in gen:
            b = emit(cand)
            if b is not None:
                yield b
                n += 1
                stall = 0
            else:
                stall += 1
                if stall >= STALL_LIMIT:
                    return
            if n >= cap or len(seen) >= max_boards:
                return

    # A2 first — the empty-slot variants are few (~C(n,1..3)) and must not be starved by A.
    def _drops():
        for drop in (1, 2, 3):
            if len(base) - drop < 1:
                break
            for combo in itertools.combinations(range(len(base)), len(base) - drop):
                yield [base[i] for i in combo]
    yield from run(_drops(), max_boards)

    # A — permutations of the played board (full perms if small, else random shuffles), ~40% of budget.
    def _perms():
        if len(base) <= 6:
            yield from (list(p) for p in itertools.permutations(base))
        else:
            while True:
                s = base[:]; random.shuffle(s); yield s
    yield from run(_perms(), max(1, int(max_boards * 0.4)))

    # B — replace one played card with one pool card.
    def _swaps():
        for i in range(len(base)):
            for hc in extra:
                s = base[:]; s[i] = hc; yield s
    yield from run(_swaps(), max_boards)

    # C — random deck-sized subsets of the full pool, fill whatever budget remains.
    full = base + extra
    def _subsets():
        while full:
            random.shuffle(full)
            yield full[:max(1, min(deck_slots, len(full)))]
    yield from run(_subsets(), max_boards)


def _my_candidates(board, hand, slots, cap):
    """Candidate MY boards from board + hand, FULL-BOARD-FIRST. Most candidates fill
    all available slots (= min(unlocked, cards I have)); only a small minority are
    "drop" boards (fewer cards), kept just so empty-slot-scaling cards (逍遥无影拳
    etc.) can still be found. Leading with drops over-recommended under-full boards
    when no empty-slot synergy was present — this fixes that bias."""
    board = [c for c in board if c]
    hand = [c for c in hand if c and c not in board]
    avail = board + hand
    if not avail:
        return [board] if board else []
    full_size = min(slots, len(avail))
    seen, out = set(), []

    def emit(b):
        b = [c for c in b if c]
        if not b:
            return False
        t = tuple(b)
        if t in seen:
            return False
        seen.add(t)
        out.append(b)
        return True

    emit(board)                              # the current board first
    full_budget = max(2, int(cap * 0.85))    # ~85% of the budget = full-size boards

    # Full-size hand swaps: replace one board card with one hand card.
    swaps = [(i, hc) for hc in hand for i in range(len(board))]
    random.shuffle(swaps)
    for i, hc in swaps:
        if len(out) >= full_budget:
            break
        b = board[:]
        b[i] = hc
        emit(b)
    # Full-size subsets/permutations of board+hand (bounded attempts).
    attempts = 0
    while len(out) < full_budget and attempts < cap * 8:
        attempts += 1
        random.shuffle(avail)
        emit(avail[:full_size])

    # Drop boards (minority): fewer cards → more empty slots, for empty-slot cards.
    if len(board) >= 2:
        for drop in (1, 2):
            if full_size - drop < 1:
                break
            combos = list(itertools.combinations(range(len(board)), len(board) - drop))
            random.shuffle(combos)
            for combo in combos:
                if len(out) >= cap:
                    break
                emit([board[i] for i in combo])
            if len(out) >= cap:
                break
    return out[:cap]


def _player(side: dict) -> dict:
    """Normalize a live-state side dict to the Oracle's NativeFixturePlayer fields.
    Required: characterId, usedCards(board ids). Optional but damage-relevant: level(realm 1..5),
    extraMaxHp, talents(ids), fateStrategies(ids), sect, career, life, unlockGrids."""
    return {
        "characterId": side.get("characterId", 0),
        "level": side.get("level", 0),
        # exp == cultivation (修为): the engine reads characterUI.exp as cultivation
        # for cultivation-scaling cards. Previously unset (read 0 → silent under-damage).
        "exp": side.get("exp", 0),
        "sect": side.get("sect", 0),
        "career": side.get("career", 0),
        "life": side.get("life", 100),
        "extraMaxHp": side.get("extraMaxHp", 0),
        "unlockGrids": side.get("unlockGrids", 8),
        "usedCards": list(side.get("usedCards", [])),
        "talents": list(side.get("talents", [])),
        "fateStrategies": list(side.get("fateStrategies", [])),
        # Per-battle buff/talent instance state (closes most of the state gap vs a bare board).
        "usedKeYinCards": list(side.get("usedKeYinCards", [])),
        "permanentBuffTempDatas": dict(side.get("permanentBuffTempDatas", {})),
        "talentTempDatas": dict(side.get("talentTempDatas", {})),
        "resonanceTalentFlags": dict(side.get("resonanceTalentFlags", {})),
        "talentDatas": dict(side.get("talentDatas", {})),
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


def live_best_lines(me: dict, opp: dict, opp_boards_by_round,
                    *, my_hand=None, rnd: int = 8, fast: bool = True, top_k: int = 3,
                    my_max_boards: int = None, opp_max_boards: int = None,
                    use_heuristics: bool = False, opp_seed_extra=None, rng=None):
    """Live "best line" as a mixed-strategy (Nash) game — step 4 of the live calc.

    me                  live ME fixture (usedCards = my CURRENT board).
    opp                 live OPP fixture (last-seen). Projected +5 exp(cultivation)
                        / +2 extraMaxHp here to estimate one round of growth.
    opp_boards_by_round list of the opponent's boards (each a list of card ids) over
                        the last <=3 rounds — the basis for their card pool.

    Builds my candidate boards from my current cards and the opponent's from their
    pooled cards, scores every pairing through the Oracle (payoff = my margin:
    lifeDamage, hp as tie-break), solves the zero-sum equilibrium, and returns the
    top lines + a probability-weighted highlighted pick.

    Returns {lines:[{slots,board,probability}], pick_index, pick_board, value,
    opp_pool_size, tried} or {error}/None. Pure add-on: nothing calls this yet —
    it's wired into the live push behind a flag in a later step.
    """
    import live_nash
    try:
        import heuristic_lines as HL
    except Exception:
        HL = None

    mp = _player(me)
    op = live_nash.project_opponent(_player(opp))   # +5 exp / +2 hp (opponent only)

    my_board = [c for c in mp["usedCards"] if c]
    if not my_board:
        return {"error": "no current board for me"}
    opp_pool = live_nash.opponent_pool_cards(opp_boards_by_round or [], _line_of, _level_of)
    opp_last = [c for c in (opp_boards_by_round[-1] if opp_boards_by_round else []) if c] \
        or list(dict.fromkeys(opp_pool))
    if not opp_last:
        return {"error": "no opponent board history"}

    my_slots = int(mp.get("unlockGrids", 8) or 8)
    opp_slots = int(op.get("unlockGrids", 8) or 8)
    # My candidates are arrangements of my CURRENT board PLUS my hand — the best
    # line often means placing/swapping in a hand card, not just rearranging the
    # board. With a wider card pool the candidate set needs to be larger than the
    # board-only case (where ~6 sufficed), so my rows scale up here. Opponent
    # column coverage still matters most (handled by the best-response guard).
    my_hand_ids = [int(c) for c in (my_hand or []) if c]
    my_cap = my_max_boards if my_max_boards is not None else (12 if fast else 24)
    opp_cap = opp_max_boards if opp_max_boards is not None else (18 if fast else 30)

    my_char = int(me.get("characterId", 0) or 0)
    my_career = int(me.get("career", 0) or 0) or None
    opp_char = int(opp.get("characterId", 0) or 0)
    my_realm = int(mp.get("level", 0) or 0) or None
    opp_realm = int(op.get("level", 0) or 0) or None

    def _dedup(boards):
        seen, out = set(), []
        for b in boards:
            b = [c for c in b if c]
            t = tuple(b)
            if b and t not in seen:
                seen.add(t)
                out.append(b)
        return out

    # MY candidate pool: full-board-first arrangements of board + hand. My career
    # IS known (is_me), so heuristic COMMON full boards for my char/career/realm —
    # filtered to cards I actually hold — seed the search with a known-strong full
    # board (and join the pool the my-side best-response can pick from).
    my_boards = _my_candidates(my_board, my_hand_ids, my_slots, my_cap)
    my_seed = [my_board]
    if HL is not None and HL.available():
        my_counts = live_nash.build_opponent_pool(
            [my_board + my_hand_ids], _line_of, _level_of)
        legal_common = [b for b in HL.common_boards(my_char, my_career, my_realm, top=8)
                        if live_nash.pool_legal(b, my_counts, _line_of, _level_of)]
        my_seed = _dedup([my_board] + legal_common[:2])
        my_boards = _dedup(my_boards + legal_common)

    # OPPONENT columns: their actual last board + pool arrangements. The
    # best-response guard then searches these for the punishing counter.
    #
    # Heuristic counter/common boards (the season build data) are added ONLY after
    # filtering to the opponent's observed pool via pool_legal — so we get the
    # realistic strong compositions/orderings the archetype plays WITHOUT phantom
    # counters built from cards the opponent doesn't hold (unconstrained heuristics
    # recommended losing lines in the replay validation). opp career isn't on the
    # wire → aggregate across careers.
    heur = []
    if use_heuristics and HL is not None and HL.available():
        pool_counts = live_nash.build_opponent_pool(opp_boards_by_round or [], _line_of, _level_of)
        raw_heur = (HL.counter_boards(opp_char, None, my_char, top=8)
                    + HL.common_boards(opp_char, None, opp_realm, top=6))
        heur = [b for b in raw_heur
                if live_nash.pool_legal(b, pool_counts, _line_of, _level_of)]
    pool_arrangements = list(_candidates(opp_last, list(opp_last) + list(opp_pool), opp_slots, opp_cap))
    # opp_seed_extra = the opponent's good boards from a prior calc (warm start when
    # only MY cards changed — their playable set is unchanged within a round).
    warm = [b for b in (opp_seed_extra or []) if b]
    opp_candidates = _dedup([opp_last] + warm + heur + pool_arrangements)
    # Seed columns: last board + warm columns + top heuristic counters.
    opp_seed = _dedup([opp_last] + warm + heur[:3])

    # The whole search must hold the worker lock — a concurrent matchup() would
    # corrupt the single stdin/stdout pipe (same constraint as whatif_from_stat).
    with _lock:
        w = _get_worker()
        if w is None:
            return None

        def _run(p1cards, p2cards):
            fx = {"p1": {**mp, "usedCards": list(p1cards)},
                  "p2": {**op, "usedCards": list(p2cards)},
                  "battleParams": [], "mainViewId": "", "round": rnd, "expected": {},
                  "wantLog": False}
            return w.run(fx)

        # payoff = my margin from p1's perspective: destiny (命) damage dominates,
        # board hp advantage breaks ties between boards that deal the same life dmg,
        # and finally MORE CARDS breaks a true tie (same life + same hp) — so an
        # equally-good line fills the board rather than leaving slots empty for no
        # benefit. The +card term (1e-4) is below the hp step (1e-3), so it never
        # overrides a real difference, only a genuine tie.
        def evaluate(mb, ob):
            r = _run(mb, ob)
            return (float(r.get("lifeDamage", 0) or 0)
                    + float(r.get("hpDelta", 0) or 0) / 1000.0
                    + len([c for c in mb if c]) * 1e-4)

        try:
            # Two-sided best-response: my side AND the opponent each best-respond to
            # the equilibrium each round, so my strong full board is discovered even
            # if it wasn't seeded (and the opponent's counter is still found).
            res, opp_res, my_rows, cols, cache, iterations = live_nash.solve_double_oracle(
                my_seed, my_boards, opp_seed, opp_candidates, evaluate,
                iters=1500, top_k=top_k, rng=rng)
        except Exception as e:
            _reset_worker()
            return {"error": f"live_best_lines failed: {e}"}

    def _lines(nash):
        return [{"slots": [_slot(c) for c in ln.board], "board": ln.board,
                 "probability": round(ln.probability, 4)} for ln in nash.top]

    return {
        "lines": _lines(res),
        "pick_index": (res.pick.index if res.pick else -1),
        "pick_board": (res.pick.board if res.pick else None),
        "value": res.value,
        # The opponent's predicted play — their equilibrium mix over the boards the
        # guard surfaced (the strongest counters to my line).
        "opp_lines": _lines(opp_res),
        "opp_pick_board": (opp_res.pick.board if opp_res.pick else None),
        # the active opponent columns — fed back as opp_seed_extra to warm-start
        # the next calc when only my cards change.
        "opp_active_boards": cols,
        "opp_pool_size": len(opp_pool),
        "my_rows_active": len(my_rows),
        "my_cands": len(my_boards),
        "opp_cols_considered": len(opp_candidates),
        "opp_cols_active": len(cols),
        "iterations": iterations,        # double-oracle best-response rounds
        "oracle_evals": len(cache),
        # sim-input stats (for the UI's "everything working?" readout): cultivation
        # (exp) and realm the calc actually fed the engine; opp values are PROJECTED.
        "me_cult": int(mp.get("exp", 0) or 0),
        "me_realm": int(mp.get("level", 0) or 0),
        "opp_cult": int(op.get("exp", 0) or 0),
        "opp_realm": int(op.get("level", 0) or 0),
    }


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
    me = desc.get(my_side, {})
    board = me.get("usedCards", []) or []
    if not board:
        return {"error": "no board for my side"}
    # For the go-first fallback: my uid (vs the recorded firstPlayerId tells whether I already went
    # first) and my hand size (cards I could absorb for +1 cultivation each to take the first turn).
    my_uid = me.get("uid", "")
    my_hand = int(me.get("handCards", 0) or 0)
    recorded_first = bool(my_uid) and desc.get("firstPlayerId") == my_uid

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

    # No win going second (recorded turn order). The player may still win by going FIRST: in 弈仙牌 the
    # higher-cultivation player takes the first turn, and absorbing a card grants +1 cultivation — so a
    # player still holding cards can choose to go first. Only worth checking if I did NOT already go
    # first in the record. Re-run the boards (played board + candidates) forcing me first; if one wins
    # AND my hand has cards to absorb for the cultivation, surface it as a go-first line.
    if not recorded_first:
        gf_boards = [board] + cands
        gf = w.run({"id": slot_id, "round": rnd, "side": my_side,
                    "firstSide": my_side, "boards": gf_boards}).get("results", [])
        for i, r in enumerate(gf):
            if sign * r[2] > 0:                      # a board that wins the round going first
                if my_hand > 0:                      # enough cards in hand to absorb → go first is achievable
                    wb = gf_boards[i]
                    return {
                        "win": True, "outcome": "win", "requires_go_first": True,
                        "hand_cards": my_hand, "tried": tried + len(gf_boards),
                        "original_life": orig_life, "original_hpDelta": orig_hp,
                        "winning_slots": [_slot(c) for c in wb],
                        "end_turn": gf[i][1], "my_side": my_side,
                        "used_hand": any(c not in board for c in wb),
                    }
                break                                # winnable first, but no cards to absorb → not achievable
    return {
        "win": False, "tried": tried,
        "original_life": orig_life, "original_hpDelta": orig_hp,
        "closest_life": best_life, "closest_hpDelta": best_hp,
        "my_side": my_side,
    }
