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
import time
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


# ── board-type legality: ≤2 [消耗] and ≤2 [持续] cards per board ─────────────────────────────
# Separate per-type caps, verified on 463k replay boards (99.7% comply; the rare
# exceptions correlate with career perks — >2 消耗 only 炼丹师/符箓师, >2 持续 mostly
# 阵法师/琴师). Without this filter the candidate generator happily builds 3-pill
# boards the game won't allow — and the engine scores them optimistically, so they
# WIN the ranking and surface as illegal suggestions.
_card_types_cache = None


def _card_types():
    """(consumption_lines, continuous_lines) from proxy/card_types.json (generated
    by tools/gen_card_types.py from the game db's [消耗]/[持续] desc markers).
    Missing/broken file -> empty sets = filtering disabled, prior behavior."""
    global _card_types_cache
    if _card_types_cache is None:
        try:
            import json
            d = json.loads((_BASE / "card_types.json").read_text(encoding="utf-8"))
            _card_types_cache = (frozenset(d.get("consumption") or []),
                                 frozenset(d.get("continuous") or []))
        except Exception:
            _card_types_cache = (frozenset(), frozenset())
    return _card_types_cache


def _concon(board):
    """(#消耗, #持续) copies on a board — per COPY, line-level flags."""
    cons, cont = _card_types()
    nc = nt = 0
    for c in board or []:
        if not c:
            continue
        ln = _line_of(c)
        nc += ln in cons
        nt += ln in cont
    return nc, nt


def _concon_caps(*observed_boards):
    """Legal (消耗_cap, 持续_cap), self-calibrating: strict 2/2 unless one of the
    OBSERVED live boards already legally exceeds a cap (career perks can raise it;
    we trust what the game itself allowed rather than modeling each perk)."""
    cons_cap = cont_cap = 2
    for b in observed_boards:
        if not b:
            continue
        nc, nt = _concon(b)
        cons_cap = max(cons_cap, nc)
        cont_cap = max(cont_cap, nt)
    return cons_cap, cont_cap


def _concon_ok(board, caps):
    nc, nt = _concon(board)
    return nc <= caps[0] and nt <= caps[1]


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
            _get_pool()                     # pre-spawn the parallel eval pool too
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


# ── parallel evaluation pool ──────────────────────────────────────────────────
# Extra Oracle workers for BATCH matchup evaluation. The live search fires
# ~1.6-2K combats per pass; through the single main pipe that's the whole
# latency. Tier-1 pruning and mix-ranking know all their (my_board, opp_board)
# pairs upfront — embarrassingly parallel. Each worker is its own process +
# pipe (below-normal priority, ~130MB); size via ORACLE_POOL env, default
# min(6, cpu//3). Workers are spawned in parallel and pre-warmed at app start.
_pool: list = []
_pool_failed = False


def _get_pool():
    global _pool, _pool_failed
    if _pool or _pool_failed:
        return _pool
    with _lock:
        if _pool or _pool_failed:
            return _pool
        if not _oracle_exe().exists():
            _pool_failed = True
            return _pool
        try:
            if str(_ORACLE_SCRIPTS) not in sys.path:
                sys.path.insert(0, str(_ORACLE_SCRIPTS))
            from oracle_pool import OracleWorker
            n = int(os.environ.get("ORACLE_POOL", 0) or 0)
            if n <= 0:
                n = min(6, max(2, (os.cpu_count() or 8) // 3))
            slots = [None] * n
            _warm_fx = {"p1": {"characterId": 2000001, "level": 1, "exp": 0,
                               "usedCards": [4000003], "talents": [],
                               "fateStrategies": [], "career": 0,
                               "extraMaxHp": 0, "unlockGrids": 3},
                        "battleParams": [], "mainViewId": "", "round": 1,
                        "expected": {}, "wantLog": False}
            _warm_fx["p2"] = dict(_warm_fx["p1"])

            def mk(i):
                try:
                    wk = OracleWorker()
                    wk.run(dict(_warm_fx))   # pre-JIT: first combat is ~10x slower
                    slots[i] = wk
                except Exception:
                    slots[i] = None
            ts = [threading.Thread(target=mk, args=(i,), daemon=True)
                  for i in range(n)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            _pool = [w for w in slots if w is not None]
            if _pool:
                print(f"[oracle] eval pool ready: {len(_pool)} workers", flush=True)
            else:
                _pool_failed = True
        except Exception as e:
            print(f"[oracle] eval pool unavailable ({e}); sequential evals", flush=True)
            _pool_failed = True
        return _pool


def _eval_batch(pairs, mp, op, rnd, cache):
    """Evaluate (my_board, opp_board) fixtures in PARALLEL across the pool,
    filling `cache` with (life, score) — the same values _eval computes. Cached
    pairs are skipped; with no pool it quietly falls back to the main worker
    (caller must hold _lock, which it always does inside live_best_lines)."""
    def key(mb, ob):
        return (tuple(mb), tuple(ob))

    def fixture(mb, ob):
        return {"p1": {**mp, "usedCards": list(mb)},
                "p2": {**op, "usedCards": list(ob)},
                "battleParams": [], "mainViewId": "", "round": rnd,
                "expected": {}, "wantLog": False}

    def value(mb, r):
        life = float(r.get("lifeDamage", 0) or 0)
        return (life, life + float(r.get("hpDelta", 0) or 0) / 1000.0
                + len([c for c in mb if c]) * 1e-4,
                float(r.get("turns", 64) or 64))

    todo, seen = [], set()
    for mb, ob in pairs:
        k = key(mb, ob)
        if k in cache or k in seen:
            continue
        seen.add(k)
        todo.append((k, mb, ob))
    if not todo:
        return
    pool = _get_pool()
    if pool and len(todo) > 1:
        import queue
        q = queue.Queue()
        for item in todo:
            q.put(item)
        results = {}

        def loop(wk):
            while True:
                try:
                    k, mb, ob = q.get_nowait()
                except queue.Empty:
                    return
                try:
                    results[k] = value(mb, wk.run(fixture(mb, ob)))
                except Exception:
                    q.put((k, mb, ob))   # dead worker: hand back, let others drain
                    return
        ts = [threading.Thread(target=loop, args=(wk,), daemon=True)
              for wk in pool[:len(todo)]]      # no idle threads on tiny batches
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        cache.update(results)
    # anything uncovered (no pool / dead workers) → main worker, sequential
    w = _get_worker()
    for k, mb, ob in todo:
        if k not in cache and w is not None:
            try:
                cache[k] = value(mb, w.run(fixture(mb, ob)))
            except Exception:
                pass


def available() -> bool:
    """True if the Oracle engine is built and a worker can be reached."""
    return _get_worker() is not None


def shutdown():
    global _worker, _pool
    if _worker is not None:
        try:
            _worker.close()
        except Exception:
            pass
        _worker = None
    for wk in _pool:
        try:
            wk.close()
        except Exception:
            pass
    _pool = []


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
    # Board-type legality (≤2 消耗 / ≤2 持续; cap raised to what the played board
    # already legally showed) — swap/subset phases can otherwise assemble illegal builds.
    caps = _concon_caps(base)

    def emit(b):
        key = tuple(b)
        if key in seen or not b:
            return None
        seen.add(key)
        if not _concon_ok(b, caps):
            return None
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


def _my_candidates(board, hand, slots, cap, caps=None):
    """Candidate MY boards = card SETS chosen from board + hand — the FULL build
    space, not just changes from the current/last board. Enumerating sets makes the
    search independent of how my cards are currently arranged and UNBIASED toward my
    last board (the old ±1-2-card-from-base version generated only near-identical
    builds — verified missing 0/10 of the genuinely best builds, often radically
    different ones). Deterministic (no randomness). One canonical ordering per set
    (order in board+hand); ordering search is a separate concern.

    Enumerates every full-size build (board+hand choose min(slots, n)); if that
    exceeds `cap`, takes a deterministic STRIDE across the whole combination space
    (not the first `cap`, which would bias toward early cards). A few drop builds
    (one fewer card) are appended for empty-slot lines.

    caps = (消耗_cap, 持续_cap) board-type legality (see _concon_caps); builds over
    a cap are skipped. If the filter would leave NOTHING (pathological pill-heavy
    pool), falls back to unfiltered so the calc never goes dark."""
    from math import comb
    # Available pool = board cards + ALL hand cards. A hand card is a SEPARATE physical
    # card from one on the board, so DUPLICATES must be kept (id already on board is not a
    # reason to drop the hand copy) — else a held duplicate (very common early, drafting
    # pairs to merge) is invisible and the board can't be filled (recommends N-1 cards).
    avail = [c for c in board if c] + [c for c in hand if c]
    if not avail:
        return []
    n = len(avail)
    full = min(slots, n)
    seen, out = set(), []

    def emit(idxs):
        b = [avail[i] for i in idxs]
        t = tuple(b)
        if b and t not in seen and len(out) < cap:
            if caps is not None and not _concon_ok(b, caps):
                return
            seen.add(t)
            out.append(b)

    total = comb(n, full)
    if total <= cap:
        for combo in itertools.combinations(range(n), full):
            emit(combo)
    else:
        # Deterministic spread across all combinations (stride), so coverage isn't
        # biased to early-indexed cards. (combinations() is lexicographic.)
        all_combos = list(itertools.combinations(range(n), full))
        step = max(1, total // cap)
        for i in range(0, total, step):
            emit(all_combos[i])
            if len(out) >= cap:
                break
    # Drop builds (one fewer card) for empty-slot-scaling cards, with leftover budget.
    if full >= 2 and len(out) < cap:
        dn = max(1, cap // 8)
        for combo in itertools.combinations(range(n), full - 1):
            before = len(out)
            emit(combo)
            if len(out) > before:
                dn -= 1
            if dn <= 0 or len(out) >= cap:
                break
    if not out and caps is not None:      # pathological pool (e.g. all pills): keep working
        return _my_candidates(board, hand, slots, cap, caps=None)
    return out


def _best_ordering(board, value_fn, max_passes=4, deep=False, deadline=None,
                   prefetch=None):
    """Hill-climb the cyclic ORDER of a card set to maximize value_fn(order).
    The board LOOPS (slot 8 -> slot 1), so sequencing = a cycle + a starting slot.
    Moves: ROTATION scan (same cycle, different opening), pairwise SWAPs
    (first-improvement), and with deep=True single-card INSERTIONs — the move class
    that recovers combo lines. Swap+insertion run to convergence reached the true
    8!-enumerated optimum on the exact-checked validation boards (test_hk_order.py);
    here passes are bounded for latency. `deadline` (time.monotonic) hard-bounds the
    search — per-battle sim cost varies ~2-30ms with comp weight, so an un-budgeted
    deep search can pin a core for 30s+ on stack-heavy matchups and lag the game.
    `prefetch(orders)`: optional hook that bulk-evaluates candidate orders across
    the worker pool BEFORE the sequential walk — the whole neighborhood is known
    upfront, so value_fn then hits cache instead of paying one round-trip per move
    (accepted moves invalidate later prefetches; those fall back to per-call).
    Returns (ordered, value); value_fn caches."""
    cur = list(board)
    cur_v = value_fn(cur)
    n = len(cur)

    def timeup():
        return deadline is not None and time.monotonic() > deadline

    def pf(orders):
        if prefetch is not None and orders:
            try:
                prefetch(orders)
            except Exception:
                pass

    pf([cur[k:] + cur[:k] for k in range(1, n)])
    for k in range(1, n):                    # rotation scan: pick the opening
        if timeup():
            return cur, cur_v
        rot = cur[k:] + cur[:k]
        v = value_fn(rot)
        if v > cur_v + 1e-9:
            cur, cur_v = rot, v
    for _ in range(max_passes):
        improved = False
        swaps = []
        for i in range(n):
            for j in range(i + 1, n):
                cand = cur[:]
                cand[i], cand[j] = cand[j], cand[i]
                swaps.append(cand)
        pf(swaps)                            # whole swap neighborhood in parallel
        for i in range(n):
            if timeup():
                return cur, cur_v
            for j in range(i + 1, n):
                cur[i], cur[j] = cur[j], cur[i]
                v = value_fn(cur)
                if v > cur_v + 1e-9:
                    cur_v = v
                    improved = True          # first-improvement: keep the swap
                else:
                    cur[i], cur[j] = cur[j], cur[i]   # revert
        if deep:
            inss = []
            for i in range(n):
                for j in range(n):
                    if i == j:
                        continue
                    cand = cur[:]
                    cand.insert(j, cand.pop(i))
                    inss.append(cand)
            pf(inss)                         # insertion neighborhood in parallel
            for i in range(n):               # insertions: shift one card elsewhere
                if timeup():
                    return cur, cur_v
                for j in range(n):
                    if i == j:
                        continue
                    cand = cur[:]
                    cand.insert(j, cand.pop(i))
                    v = value_fn(cand)
                    if v > cur_v + 1e-9:
                        cur, cur_v, improved = cand, v, True
        if not improved:
            break
    return cur, cur_v


def _opp_candidates(history_boards, slots, cap):
    """DETERMINISTIC opponent candidate boards (no randomness). The most realistic
    predictions are the boards the opponent ACTUALLY played over the last <=3
    rounds, so we use those real arrangements first, then systematic single swaps
    among the union of cards they've shown, then single drops — fixed order.
    Generated variants respect board-type legality (≤2 消耗 / ≤2 持续, cap raised
    to whatever their REAL boards already showed — those are ground truth)."""
    boards = [[c for c in b if c] for b in (history_boards or []) if any(b)]
    caps = _concon_caps(*boards)
    seen, out = set(), []

    def emit(b):
        b = [c for c in b if c]
        if not b or len(out) >= cap:
            return
        if not _concon_ok(b, caps):
            return
        t = tuple(b)
        if t not in seen:
            seen.add(t)
            out.append(b)

    for b in reversed(boards):               # actual recent boards, newest first
        emit(b)
    base = boards[-1] if boards else []
    pool = []
    for b in boards:
        for c in b:
            if c not in pool:
                pool.append(c)
    extra = [c for c in pool if c not in base]
    for i in range(len(base)):               # single swaps from their wider pool
        for ec in extra:
            if len(out) >= cap:
                return out
            b = base[:]; b[i] = ec; emit(b)
    for i in range(len(base)):               # single drops
        if len(out) >= cap:
            return out
        emit(base[:i] + base[i + 1:])
    return out or ([base] if base else [])


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


def _model_opp_prediction(opp, opp_char, opp_realm, opp_last,
                          my_boards_by_round, opp_boards_by_round, rnd, top_k, me=None):
    """Stage-1 via the trained board-decoder: the opponent's most LIKELY next boards
    (behavioral prediction from season-9 replays), as (candidates, probabilities).

    The model predicts a self-record SUBJECT — here that subject is the LIVE OPPONENT.
    Their own board history = the opponent's boards; the boards they 'faced' = MY boards
    (people position cards in response to what the opponent — me — last played). Returns
    None on any gap (no model, torch missing, empty history) so the caller falls back to
    the Oracle game-theoretic stage 1.

    Opponent 天命 (fates) and 天衍 (derivations) ARE on the wire — the opp fixture's
    `talents`/`fateStrategies` (GameStatus f200[5]/[16]) — so we feed them (same id space
    as the model's replay-trained vocab). Only 副职 (career) isn't broadcast for the
    opponent, so it stays 0 (the model was trained with a real career; 0 = unknown)."""
    try:
        import board_model
    except Exception:
        return None
    if not board_model.available():
        return None
    obr = [[int(c) for c in b if c] for b in (opp_boards_by_round or []) if b]
    mbr = [[int(c) for c in b if c] for b in (my_boards_by_round or []) if b]
    try:
        preds = board_model.get_predictor().predict(
            char=int(opp_char or 0), career=int(opp.get("career", 0) or 0),
            realm=int(opp_realm or 0), rnd=int(rnd),
            cur_board=opp_last,                       # opponent's CURRENT board
            opp_board=(mbr[-1] if mbr else []),       # MY last board (they react to me)
            fates=[int(t) for t in (opp.get("talents") or [])],          # 天命 (on wire)
            derivs=[int(d) for d in (opp.get("fateStrategies") or [])],  # 天衍 (on wire)
            # v3: MY plan — the opponent reacts to the player they face (us).
            faced_fates=[int(t) for t in ((me or {}).get("talents") or [])],
            faced_derivs=[int(d) for d in ((me or {}).get("fateStrategies") or [])],
            own_hist=(obr[-2] if len(obr) >= 2 else [], obr[-3] if len(obr) >= 3 else []),
            opp_hist=(mbr[-2] if len(mbr) >= 2 else [], mbr[-3] if len(mbr) >= 3 else []),
            top_k=20)      # many lines, weighted by model confidence (nucleus-adaptive)
    except Exception:
        return None
    if not preds:
        return None
    cands = [b for b, _ in preds if b]
    strat = [p for b, p in preds if b]
    return (cands, strat) if cands else None


def live_best_lines(me: dict, opp: dict, opp_boards_by_round,
                    *, my_boards_by_round=None, my_hand=None, rnd: int = 8,
                    fast: bool = True, top_k: int = 3,
                    my_max_boards: int = None, opp_max_boards: int = None,
                    use_heuristics: bool = False, opp_seed_extra=None, rng=None,
                    use_board_model=None):
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
    # Round-aware growth: +4 exp rounds 1-6 (one draw fills the new board slot),
    # +5 rounds 7-11, +6 rounds 12+ (extra draw); +2 hp/round. Opponent only.
    op = live_nash.project_opponent(_player(opp), rnd=rnd)

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
    # my_build_cap = how many of MY candidate builds (card-set space) to score. The
    # FINAL pass enumerates the whole space for a typical board+hand (C(12,8)=495);
    # the fast pass strides a sample. my_pred_cap = the opponent's model of me (kept
    # small). opp_cap = the opponent's own candidate boards.
    my_build_cap = my_max_boards if my_max_boards is not None else (64 if fast else 512)
    my_pred_cap = 16 if fast else 48
    opp_cap = opp_max_boards if opp_max_boards is not None else (12 if fast else 24)

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

    # MY candidate builds = the FULL card-set space from my board + hand. Set
    # enumeration is inherently base-independent, so the result no longer depends on
    # my last board or my current arrangement (#3), and it covers builds very
    # different from what I last played (#2 — the old ±-from-base search missed them).
    # Board-type legality caps for MY builds: strict ≤2 消耗 / ≤2 持续 unless my own
    # live boards this game already legally exceed a cap (career perk — trust the game).
    my_caps = _concon_caps(my_board, *(my_boards_by_round or []))
    my_boards = _my_candidates(my_board, my_hand_ids, my_slots, my_build_cap,
                               caps=my_caps)

    # Put every candidate SET into its HELD-KARP cycle order (exact max-weight
    # Hamiltonian cycle under adjacency weights learned from winning replay boards;
    # the board loops 8->1, so ordering IS a cycle). Microseconds per set, no combat.
    # Two effects (validated in test_hk_order.py — HK order beats the strong player's
    # own order on 80% of held-out rounds): (a) Tier-1 ranks each set near its best
    # order instead of pool order, so a strong build no longer loses its slot to a
    # lucky-ordered weak one; (b) the Tier-2 ordering search starts from a good seed.
    try:
        import hk_order
        if my_boards and hk_order.available():
            my_boards = [b for b, _v in hk_order.best_cycles(my_boards)]
    except Exception:
        pass

    # OPPONENT candidates — DETERMINISTIC: their actual recent boards + systematic
    # swaps from the cards they've shown (no random sampling → seed-independent).
    warm = [b for b in (opp_seed_extra or []) if b]
    pool_arrangements = _opp_candidates(opp_boards_by_round or [[c for c in opp_last]],
                                        opp_slots, opp_cap)
    opp_candidates = _dedup([opp_last] + warm + pool_arrangements)

    # ── #2: MY PREDICTED boards as the OPPONENT sees me — built from MY last <=3
    # rounds (the only info they have). The opponent can't see my current cards, so
    # they counter my HISTORY, not my actual board. Coverage here matters: too few
    # of my plausible plays and the opponent mispredicts (drops round-9 quality).
    my_pred = _opp_candidates(my_boards_by_round or [my_board], my_slots, my_pred_cap)

    # ── STAGE 1 SOURCE — prefer the trained board-decoder (behavioral prediction of
    # what the opponent actually plays) over the Oracle game-solve. Computed outside the
    # worker lock (independent of the Oracle pipe). Falls back to the game-solve on any
    # gap. `use_board_model`: None=auto (use if the model is loadable), True/False=force.
    model_pred = None
    if use_board_model is not False:
        model_pred = _model_opp_prediction(opp, opp_char, opp_realm, opp_last,
                                           my_boards_by_round, opp_boards_by_round,
                                           rnd, top_k, me=me)
    opp_source = "model" if model_pred else "oracle"

    import time as _time
    _t0 = _time.time()
    # The whole search must hold the worker lock — a concurrent matchup() would
    # corrupt the single stdin/stdout pipe (same constraint as whatif_from_stat).
    with _lock:
        w = _get_worker()
        if w is None:
            return None
        cache = {}

        # One Oracle matchup -> (life, score, turns). `life` = MY 命 (destiny)
        # margin: >0 means I win the combat. `score` = 命 margin + board-hp
        # tiebreak + a tiny fill bonus. `turns` = combat length — used as the
        # tie-break among GUARANTEED-win candidates (kill faster > squeeze 命).
        def _eval(mb, ob):
            k = (tuple(mb), tuple(ob))
            v = cache.get(k)
            if v is None:
                fx = {"p1": {**mp, "usedCards": list(mb)},
                      "p2": {**op, "usedCards": list(ob)},
                      "battleParams": [], "mainViewId": "", "round": rnd,
                      "expected": {}, "wantLog": False}
                r = w.run(fx)
                life = float(r.get("lifeDamage", 0) or 0)
                score = life + float(r.get("hpDelta", 0) or 0) / 1000.0 \
                    + len([c for c in mb if c]) * 1e-4
                v = (life, score, float(r.get("turns", 64) or 64))
                cache[k] = v
            return v

        def evaluate(mb, ob):        # scalar 命 margin (used by the Oracle stage-1 solve)
            return _eval(mb, ob)[1]

        try:
            # STAGE 1 — predict how the opponent will play.
            if model_pred is not None:
                # Behavioral prediction from the trained decoder: MANY boards weighted by
                # the model's own confidence (adaptive count — few when it's sure, many
                # when it's open). I best-respond to the whole weighted set, so the pick
                # isn't hyper-focused on one guess. Cap the SUPPORT actually scored to the
                # top boards by weight (the low-probability tail barely moves the expected
                # value) to keep it fast; the display can still list more.
                opp_candidates, opp_strat = model_pred
                # Drop predicted boards that break board-type legality (≤2 消耗 /
                # ≤2 持续; cap raised to what their REAL boards showed). The decoder
                # occasionally assembles one — it can't be played, so hedging
                # against it wastes weight. Carry board is always legal → never empty.
                ocaps = _concon_caps(*[b for b in (opp_boards_by_round or []) if b])
                keep = [j for j in range(len(opp_candidates))
                        if _concon_ok(opp_candidates[j], ocaps)]
                if keep and len(keep) < len(opp_candidates):
                    opp_candidates = [opp_candidates[j] for j in keep]
                    opp_strat = [opp_strat[j] for j in keep]
                cap = 12 if fast else 20
                if len(opp_candidates) > cap:
                    keep = sorted(range(len(opp_candidates)),
                                  key=lambda j: -opp_strat[j])[:cap]
                    opp_candidates = [opp_candidates[j] for j in keep]
                    opp_strat = [opp_strat[j] for j in keep]
                z = sum(opp_strat) or 1.0
                opp_strat = [w / z for w in opp_strat]
                val1 = 0.0
            else:
                # Fallback: the opponent solves MY history. Zero-sum game: my predicted
                # boards (rows) vs the opponent's candidate boards (cols); they minimize
                # my margin. Their equilibrium = how they'd play vs my last rounds.
                _eval_batch([(mr, oc) for mr in my_pred for oc in opp_candidates],
                            mp, op, rnd, cache)
                P1 = [[evaluate(mr, oc) for oc in opp_candidates] for mr in my_pred]
                _r1, opp_strat, val1 = live_nash.solve_zero_sum(P1, iters=2000)
            opp_res = live_nash.likely_lines(opp_candidates, opp_strat, -val1, top_k=max(top_k, 8))

            # STAGE 2 — I best-respond to the opponent's predicted MIX (hedge). Each
            # of my candidate boards is scored by its EXPECTED margin over the
            # opponent's predicted strategy; rank by that and pick the best. The
            # opponent never sees my cards, so this is a pure best-response — not the
            # over-conservative minimax-over-all-arrangements. Only the opponent's
            # SUPPORT (boards they'd actually play, weight > 0) needs scoring.
            support = [j for j in range(len(opp_candidates)) if opp_strat[j] > 1e-6]
            top_j = max(support, key=lambda j: opp_strat[j]) if support else 0
            top_opp = opp_candidates[top_j]    # opponent's single most-likely board

            # Objective = WIN RATE first; among GUARANTEED wins (beats every predicted
            # board) the tie-break is SPEED — fewer combat turns. A fast, clean kill is
            # robust; squeezing extra 命 out of an already-won matchup tends to pick
            # fragile greed-lines that lose when the prediction is off (user-observed).
            # Below guaranteed, 命 margin stays the tie-break. Scalar layering:
            # WIN (1e6) ≫ turn bonus (≤ ~3200) ≫ 命 margin (±60).
            WIN = 1e6
            TURN_W = 50.0
            MAX_TURNS = 64.0

            def _speed_bonus(full_win, avg_turns):
                return (MAX_TURNS - avg_turns) * TURN_W if full_win else 0.0

            # ROBUST prune proxy: blend the model's most-likely board with the opponent's
            # ACTUAL last board (~76% of a board persists round-to-round — a safe prior).
            def robust_score(mb):
                l1, c1, t1 = _eval(mb, top_opp)
                l2, c2, t2 = _eval(mb, opp_last)
                wins = (1.0 if l1 > 0 else 0.0) + (1.0 if l2 > 0 else 0.0)
                return (wins * WIN
                        + _speed_bonus(wins >= 2.0, (t1 + t2) / 2.0)
                        + 0.5 * c1 + 0.5 * c2)

            # TIER 1 — pre-rank EVERY build against the robust blend. All pairs are
            # known upfront → evaluate them in parallel across the worker pool
            # (this phase is the bulk of the search's combats).
            _eval_batch([(mb, top_opp) for mb in my_boards]
                        + [(mb, opp_last) for mb in my_boards],
                        mp, op, rnd, cache)
            prelim = sorted(((mb, robust_score(mb)) for mb in my_boards),
                            key=lambda x: x[1], reverse=True)
            n_refine = 16 if fast else 32
            order_k = 2 if fast else 3
            passes = 2 if fast else 3
            refine = [mb for mb, _ in prelim[:n_refine]]

            # Which predicted boards can ANY of my top builds actually beat? A board no
            # build can win is treated as "the opponent probably doesn't have it / won't
            # play it" — dropped from the WIN objective so we maximize wins over the boards
            # we CAN beat instead of chasing a lost cause. (命 margin still counts it as a
            # tie-break, so among equal win-rates we still prefer losing to it by less.)
            _eval_batch([(mb, opp_candidates[j]) for mb in refine for j in support],
                        mp, op, rnd, cache)      # refine × support, in parallel
            winnable = {j for j in support
                        if any(_eval(mb, opp_candidates[j])[0] > 0 for mb in refine)}
            wsum = sum(opp_strat[j] for j in winnable) or 1.0

            def my_value(mb):
                # win-rate over ALL winnable boards; GUARANTEED win → kill-speed
                # tie-break (expected turns over the mix); 命 margin last
                wins = marg = tsum = 0.0
                for j in support:
                    lf, cb, tn = _eval(mb, opp_candidates[j])
                    marg += opp_strat[j] * cb
                    tsum += opp_strat[j] * tn
                    if j in winnable and lf > 0:
                        wins += opp_strat[j]
                full = wins >= wsum - 1e-9
                return (wins / wsum) * WIN + _speed_bonus(full, tsum) + marg

            # ORDERING proxy: hill-climb the arrangement against only the top few likely
            # boards (each ordering step costs |set| Oracle calls; the full 12-20-board mix
            # is far too expensive to reorder against). Final RANKING still uses the full
            # mix (my_value); this just guides the cheap inner search.
            osupp = sorted(support, key=lambda j: -opp_strat[j])[:3]
            osz = sum(opp_strat[j] for j in osupp) or 1.0

            def order_value(mb):
                # prefetch this order's ≤3 combats across the pool (fallback path;
                # the bulk comes prefetched per-neighborhood via order_prefetch)
                _eval_batch([(mb, opp_candidates[j]) for j in osupp],
                            mp, op, rnd, cache)
                wins = marg = tsum = 0.0
                for j in osupp:
                    lf, cb, tn = _eval(mb, opp_candidates[j])
                    marg += opp_strat[j] * cb
                    tsum += opp_strat[j] * tn
                    if j in winnable and lf > 0:
                        wins += opp_strat[j]
                full = wins >= osz - 1e-9
                return (wins / osz) * WIN + _speed_bonus(full, tsum / osz) + marg

            def order_prefetch(orders):
                # bulk-load a whole move neighborhood (dozens of orders × top-3
                # opponents) across the pool in one go — the ordering phase's
                # sequential round-trips were the last big latency chunk
                _eval_batch([(o, opp_candidates[j]) for o in orders for j in osupp],
                            mp, op, rnd, cache)

            # TIER 2 — order the top builds (cheap proxy), then rank all by the FULL mix.
            # Candidates arrive in HK-cycle order (near-good seed); the search adds
            # rotations always, and INSERTION moves on the final pass — the move class
            # that recovers combo lines (certified to reach the 8! optimum on the
            # exact-checked validation boards). The ordering phase shares one TIME
            # BUDGET: per-battle sim cost varies ~2-30ms with comp weight, and without
            # a budget the deep search pins a core for 30s+ on heavy matchups.
            order_deadline = time.monotonic() + (2.5 if fast else 8.0)
            refined = []
            for idx, mb in enumerate(refine):
                if idx < order_k:
                    mb, _ = _best_ordering(mb, order_value, max_passes=passes,
                                           deep=not fast, deadline=order_deadline,
                                           prefetch=order_prefetch)
                    # the reordered board is new to the cache — parallel-fill its
                    # full-mix pairs before the sequential my_value pass
                    _eval_batch([(mb, opp_candidates[j]) for j in support],
                                mp, op, rnd, cache)
                refined.append((mb, my_value(mb)))
            scored = sorted(refined, key=lambda x: x[1], reverse=True)
            # FINAL polish (final pass): order the top-2 winners against the proxy (cheap)
            # then re-rank all by the full mix — the winner may have risen only after mix
            # scoring and not gotten the ordering pass.
            if not fast and scored:
                polish_deadline = time.monotonic() + 4.0
                for k in range(min(2, len(scored))):
                    b, _ = _best_ordering(scored[k][0], order_value, max_passes=2,
                                          deep=True, deadline=polish_deadline,
                                          prefetch=order_prefetch)
                    _eval_batch([(b, opp_candidates[j]) for j in support],
                                mp, op, rnd, cache)
                    scored[k] = (b, my_value(b))
                scored.sort(key=lambda x: x[1], reverse=True)
            # Human-readable display for the top lines (under the lock; the ranking scalar
            # win·1e6+命 isn't readable): expected 命 margin AND win-rate vs the predicted
            # mix. win-rate here is over ALL predicted boards (honest P(win)), not just the
            # winnable subset used for ranking.
            def _margin(mb):
                return sum(opp_strat[j] * _eval(mb, opp_candidates[j])[1] for j in support)
            def _winrate(mb):
                return sum(opp_strat[j] for j in support if _eval(mb, opp_candidates[j])[0] > 0)
            disp = [(mb, _margin(mb), _winrate(mb)) for mb, _ in scored[:top_k]]
        except Exception as e:
            _reset_worker()
            return {"error": f"live_best_lines failed: {e}"}
    elapsed = _time.time() - _t0

    def _my_lines(disp_list):
        out = []
        for mb, marg, wr in disp_list:
            slots = [_slot(c) for c in mb]
            # Pad to the unlocked slot count with Normal-Attack markers: an empty unlocked
            # slot fights as a 普通攻击, so the UI shows WHICH slots are 普攻 (and how many).
            slots += [{"normalAttack": True} for _ in range(max(0, my_slots - len(mb)))]
            out.append({"slots": slots, "board": mb, "unlocked": my_slots,
                        # expected 命 margin AND win-probability vs the opponent's predicted play
                        "guaranteed": round(marg, 1), "winrate": round(wr, 3),
                        "probability": 0.0})
        return out

    def _opp_lines(nash):
        return [{"slots": [_slot(c) for c in ln.board], "board": ln.board,
                 "probability": round(ln.probability, 4), "guaranteed": 0.0}
                for ln in nash.top]

    pick = disp[0][0] if disp else None
    return {
        "lines": _my_lines(disp),
        "pick_index": 0 if disp else -1,
        "pick_board": pick,
        "value": round(disp[0][1], 1) if disp else 0.0,   # top line's expected 命 margin
        "pick_winrate": round(disp[0][2], 3) if disp else 0.0,
        # The opponent's predicted play — board-decoder behavioral prediction when
        # available ("model"), else their Oracle equilibrium vs MY history ("oracle").
        "opp_source": opp_source,
        "opp_lines": _opp_lines(opp_res),
        "opp_pick_board": (opp_res.pick.board if opp_res.pick else None),
        "opp_active_boards": opp_candidates,
        "opp_pool_size": len(opp_pool),
        "my_cands": len(my_boards),
        "opp_cols_considered": len(opp_candidates),
        "opp_cols_active": len(opp_candidates),
        "iterations": 2,                 # 2-stage (opp predicts → I best-respond)
        "oracle_evals": len(cache),
        "elapsed_s": round(elapsed, 2),
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
    # PAD short variants to the recorded deck length with 0 (普攻). The primed
    # `boards` path takes the list LITERALLY as the whole deck — a 7-card list is a
    # 7-slot cycle that skips the empty slot, which is NOT how the game plays it
    # (an empty unlocked slot fires a normal attack in the rotation). Unpadded drop
    # variants scored phantom wins that lose when actually played (user-verified:
    # same 7 cards −54 unpadded vs +63 padded). The from-scratch live path pads
    # internally; only this primed path needs it explicit.
    n_slots = len(board)
    cands = [list(b) + [0] * (n_slots - len(b)) if len(b) < n_slots else list(b)
             for b in cands]
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
            "used_hand": any(c and c not in board for c in wb),
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
                        "used_hand": any(c and c not in board for c in wb),
                    }
                break                                # winnable first, but no cards to absorb → not achievable
    return {
        "win": False, "tried": tried,
        "original_life": orig_life, "original_hpDelta": orig_hp,
        "closest_life": best_life, "closest_hpDelta": best_hp,
        "my_side": my_side,
    }
