# -*- coding: utf-8 -*-
"""live_nash.py — live "best line" computation as a mixed-strategy (Nash) game.

The live calculator only sees MY current board and the opponent's board from a
PREVIOUS round. We model the upcoming fight as a simultaneous-move, ~zero-sum
game:

  * MY strategies   = candidate board arrangements of my CURRENT cards.
  * OPP strategies   = candidate boards built from the opponent's likely card
                       POOL (everything they showed over the last <=3 rounds).
  * payoff[i][j]    = the margin (life/HP damage from MY perspective) when my
                       board i meets opponent board j, scored by the Oracle.

A single round is zero-sum (I win <=> they lose), so the equilibrium is the
minimax solution — solvable without a general Nash solver. We use FICTITIOUS
PLAY (no scipy/numpy dependency; converges for zero-sum matrix games) to get my
optimal MIXED strategy: a probability over my candidate boards. We surface the
top 3 by probability and sample one (weighted) as the calculator's pick.

This module is deliberately engine-agnostic: the payoff matrix is supplied by an
injected `evaluate(my_board, opp_board) -> float`, so the Nash math and the
opponent-pool modeling are unit-testable offline (see __main__) without the
Oracle. oracle_sim wires the real evaluator in the live path.

Design decisions (confirmed):
  * payoff = continuous life/HP margin (not binary win/loss).
  * the +5 cultivation / +2 HP projection applies to the OPPONENT only — it
    estimates one round of growth, since their snapshot is a round stale while
    ours is current.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


# ── 1. Opponent card pool ─────────────────────────────────────────────────────
# A level-k card is 2^(k-1) merged level-1 copies. We count, per card LINE
# (identity ignoring level), the most level-1-equivalent copies the opponent
# committed in ANY single round — never the sum across rounds (that would treat
# a card reused each round as several copies) and never lv1+lv2 separately (the
# lv2 already contains the lv1s).

def base_copies(level: int) -> int:
    """Level-1-equivalent copies represented by one card at `level` (1->1, 2->2,
    3->4). Clamped to >=1 for malformed input."""
    try:
        return 1 << max(0, int(level) - 1)
    except Exception:
        return 1


def build_opponent_pool(boards_by_round, line_of, level_of):
    """Collapse the opponent's boards over the last <=3 rounds into a pool.

    boards_by_round  iterable of rounds; each round is an iterable of card ids
                     (falsy entries = empty slots, skipped).
    line_of(cid)     -> hashable identity of the card ignoring level.
    level_of(cid)    -> 1..3 level of the card.

    Returns {line: max_base_copies} — for each card line, the most level-1
    copies seen on a single round's board. This is the count of that line the
    opponent is assumed to still have available.
    """
    pool: dict = {}
    for board in boards_by_round:
        per_round: dict = {}
        for cid in board:
            if not cid:
                continue
            ln = line_of(cid)
            per_round[ln] = per_round.get(ln, 0) + base_copies(level_of(cid))
        for ln, copies in per_round.items():
            if copies > pool.get(ln, 0):
                pool[ln] = copies          # MAX across rounds, not sum
    return pool


def pool_legal(board, pool_counts, line_of, level_of) -> bool:
    """True if `board` can be fielded from an opponent pool of `pool_counts`
    ({line: base_copies}, from build_opponent_pool). Each card needs base_copies
    of its line; a level-k card consumes 2^(k-1). Used to keep heuristic-suggested
    boards honest — only those the opponent could actually play from the cards
    they've shown are allowed, so the guard can't optimize against a phantom
    counter built from cards the opponent doesn't hold."""
    need: dict = {}
    for cid in board:
        if not cid:
            continue
        ln = line_of(cid)
        need[ln] = need.get(ln, 0) + base_copies(level_of(cid))
    for ln, n in need.items():
        if n > pool_counts.get(ln, 0):
            return False
    return True


def opponent_pool_cards(boards_by_round, line_of, level_of):
    """Like build_opponent_pool, but returns the representative REAL card ids the
    Oracle needs (not just per-line counts).

    For each card line, keep the actual card ids from the SINGLE round where that
    line showed the most base-copies. This honors the same rule — a card reused
    every round contributes once (max, not sum), and a leveled-up card supersedes
    its lower-level appearances (the round with the lv2 wins over the round with
    two lv1s only if it has >= base-copies) — while preserving real ids/levels so
    candidate boards are playable fixtures.

    Returns a flat list of card ids (the opponent's assumed available cards).
    """
    best: dict = {}    # line -> (base_copies, [card ids])
    for board in boards_by_round:
        per_round: dict = {}
        for cid in board:
            if not cid:
                continue
            per_round.setdefault(line_of(cid), []).append(cid)
        for ln, ids in per_round.items():
            bc = sum(base_copies(level_of(c)) for c in ids)
            if bc > best.get(ln, (0, None))[0]:
                best[ln] = (bc, list(ids))
    cards: list = []
    for _ln, (_bc, ids) in best.items():
        cards.extend(ids)
    return cards


# ── 2. Opponent stat projection ───────────────────────────────────────────────
CULT_GROWTH_PER_ROUND = 5
HP_GROWTH_PER_ROUND = 2


def project_opponent(opp_fixture: dict, rounds: int = 1) -> dict:
    """Return a copy of the opponent fixture advanced `rounds` of natural growth:
    +5 cultivation and +2 max-HP per round. Applied to the OPPONENT only (their
    snapshot is stale by ~one round while our board is current).

    NB: cultivation is carried by the Oracle fixture's `exp` field (the engine
    reads characterUI.exp as cultivation — see NativeRunner cultivation-scaling
    note), so we bump `exp`, not a separate 'cultivation' key."""
    out = dict(opp_fixture)
    out["exp"] = int(out.get("exp", 0) or 0) + CULT_GROWTH_PER_ROUND * rounds
    out["extraMaxHp"] = int(out.get("extraMaxHp", 0) or 0) + HP_GROWTH_PER_ROUND * rounds
    return out


# ── 3. Zero-sum equilibrium via fictitious play ───────────────────────────────
def solve_zero_sum(payoff, iters: int = 2000):
    """Fictitious play on a zero-sum matrix game.

    payoff  M x N matrix; payoff[i][j] = ROW (me) player's gain when I play row i
            and the opponent plays column j. The opponent minimizes it.

    Returns (row_strategy, col_strategy, game_value):
      row_strategy  length-M probabilities — my optimal MIXED strategy.
      col_strategy  length-N probabilities — opponent's.
      game_value    the value of the game (my expected margin at equilibrium).

    Fictitious play converges to the value for zero-sum games (Robinson 1951);
    the empirical play frequencies converge to an equilibrium. No external deps.
    """
    M = len(payoff)
    N = len(payoff[0]) if M else 0
    if M == 0 or N == 0:
        return [], [], 0.0

    row_count = [0] * M           # times each of my rows was a best response
    col_count = [0] * N           # times each opp column was a best response
    # Running totals of payoff given the opponent's / my empirical play.
    row_payoff_vs_colhist = [0.0] * M    # my expected payoff per row vs opp history
    col_payoff_vs_rowhist = [0.0] * N    # opp's (=my) payoff per col vs my history

    # Seed: each side best-responds to a uniform-ish first move.
    col_count[0] = 1
    for i in range(M):
        row_payoff_vs_colhist[i] += payoff[i][0]

    for _ in range(iters):
        # I best-respond: pick the row maximizing payoff vs the opponent's history.
        best_i = max(range(M), key=lambda i: row_payoff_vs_colhist[i])
        row_count[best_i] += 1
        for j in range(N):
            col_payoff_vs_rowhist[j] += payoff[best_i][j]
        # Opponent best-responds: pick the column MINIMIZING my payoff vs my history.
        best_j = min(range(N), key=lambda j: col_payoff_vs_rowhist[j])
        col_count[best_j] += 1
        for i in range(M):
            row_payoff_vs_colhist[i] += payoff[i][best_j]

    total_r = sum(row_count) or 1
    total_c = sum(col_count) or 1
    row_strategy = [c / total_r for c in row_count]
    col_strategy = [c / total_c for c in col_count]
    # Game value = row strategy^T · payoff · col strategy.
    value = 0.0
    for i in range(M):
        if row_strategy[i] == 0:
            continue
        for j in range(N):
            value += row_strategy[i] * payoff[i][j] * col_strategy[j]
    return row_strategy, col_strategy, value


# ── 4. Best-line selection ────────────────────────────────────────────────────
@dataclass
class Line:
    board: list           # the candidate board (card ids)
    probability: float    # equilibrium mixing weight
    index: int            # index into the original my_boards list


@dataclass
class NashResult:
    top: list = field(default_factory=list)   # up to 3 Line, descending prob
    pick: Line | None = None                   # the weighted-random highlighted line
    value: float = 0.0                         # equilibrium margin (my expected payoff)


def best_lines(my_boards, row_strategy, value, top_k: int = 3, rng=None) -> NashResult:
    """From my equilibrium mixed strategy, return the top_k boards by probability
    and sample ONE (weighted by probability) as the highlighted pick."""
    if not my_boards or not row_strategy:
        return NashResult()
    ranked = sorted(
        (Line(board=my_boards[i], probability=p, index=i)
         for i, p in enumerate(row_strategy) if p > 0),
        key=lambda ln: ln.probability, reverse=True,
    )
    top = ranked[:top_k]
    # Weighted-random highlight over the FULL support (not just the top 3) so the
    # pick honors the true mixed strategy.
    r = (rng or random).random()
    cum = 0.0
    pick = ranked[0] if ranked else None
    for ln in ranked:
        cum += ln.probability
        if r <= cum:
            pick = ln
            break
    return NashResult(top=top, pick=pick, value=value)


def solve_with_opponent_guard(my_boards, opp_seed_boards, opp_candidate_boards, evaluate,
                              *, max_add: int = 24, iters: int = 2000, top_k: int = 3,
                              rng=None, eps: float = 1e-6):
    """Solve the (few my-rows) x (opponent-columns) game, then iteratively add the
    opponent's BEST RESPONSE — the candidate board that most punishes my current
    equilibrium line — until no candidate beats the game value. This is the fix
    for the failure the replay study exposed: a fixed/partial opponent column set
    lets the solver lock onto a tempting line whose real counter was never scored,
    so it confidently recommends a losing board. Best-response column generation
    guarantees the punishing counter is found.

    my_boards            fixed small set of MY candidate boards (rows). The study
                         showed ~2-6 suffice — opponent coverage is what matters.
    opp_seed_boards      initial opponent columns (their last board + heuristic
                         common/counter boards). Warm start so we converge fast.
    opp_candidate_boards the POOL the best-response searches over (pool arrangements
                         + heuristic boards). Must contain the real counters; this
                         is where the season9 build heuristics earn their keep.
    evaluate(mb, ob)     -> my margin. Cached by (board, board) so repeated scoring
                         is free.

    Returns (my_result, opp_result, active_opp_columns, eval_cache):
      my_result   NashResult over my_boards (my mixed strategy → top lines + pick).
      opp_result  NashResult over the active opponent columns (their equilibrium
                  mix → the boards the calc predicts they'll play, the strongest
                  counters to my line).
    eval_cache lets the caller report how many Oracle calls were actually made."""
    cache: dict = {}

    def pay(mb, ob):
        k = (tuple(mb), tuple(ob))
        v = cache.get(k)
        if v is None:
            v = float(evaluate(mb, ob))
            cache[k] = v
        return v

    cols: list = []
    seen: set = set()
    for ob in (opp_seed_boards or []):
        t = tuple(ob)
        if ob and t not in seen:
            seen.add(t)
            cols.append(ob)
    if not cols and opp_candidate_boards:
        cols.append(opp_candidate_boards[0])
        seen.add(tuple(opp_candidate_boards[0]))
    if not cols:
        return NashResult(), NashResult(), [], cache

    row, val = None, 0.0
    for _ in range(max_add):
        P = [[pay(mb, ob) for ob in cols] for mb in my_boards]
        row, _col, val = solve_zero_sum(P, iters=iters)
        # opponent best response over the WHOLE candidate pool vs my current line
        best_ob, best_ev = None, None
        for ob in (opp_candidate_boards or []):
            ev = sum(row[i] * pay(my_boards[i], ob) for i in range(len(my_boards)))
            if best_ev is None or ev < best_ev:
                best_ev, best_ob = ev, ob
        if best_ob is None or tuple(best_ob) in seen or best_ev >= val - eps:
            break                      # no unpunished counter remains → robust
        seen.add(tuple(best_ob))
        cols.append(best_ob)

    P = [[pay(mb, ob) for ob in cols] for mb in my_boards]
    row, col, val = solve_zero_sum(P, iters=iters)
    my_res = best_lines(my_boards, row, val, top_k=top_k, rng=rng)
    # Opponent's equilibrium mix over the active columns = the boards the calc
    # predicts they'll field (their value is -val from their perspective).
    opp_res = best_lines(cols, col, -val, top_k=top_k, rng=rng)
    return my_res, opp_res, cols, cache


def compute(my_boards, opp_boards, evaluate, *, iters: int = 2000,
            top_k: int = 3, rng=None) -> NashResult:
    """End-to-end: build the payoff matrix with `evaluate(my_board, opp_board)`
    (-> my margin), solve the zero-sum game, return the top lines + pick.

    `evaluate` is injected so the Oracle stays out of this module (and tests run
    offline). The caller is responsible for candidate generation and for keeping
    the matrix small enough for the latency budget."""
    if not my_boards or not opp_boards:
        return NashResult()
    payoff = [[float(evaluate(mb, ob)) for ob in opp_boards] for mb in my_boards]
    row_strategy, _col, value = solve_zero_sum(payoff, iters=iters)
    return best_lines(my_boards, row_strategy, value, top_k=top_k, rng=rng)


# ── self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Pool rule: card 10001 = line 1 lv1; 20001 = line 1 lv2 (2 copies); 10002 = line 2.
    LINE = lambda cid: cid % 10000
    LEVEL = lambda cid: (cid // 10000)
    rounds = [
        [10001, 10001, 10002],   # R-3: two copies of line 1 (lv1), one of line 2
        [20001, 10002],          # R-2: line 1 leveled to lv2 (==2 copies), line 2 again
        [10002, 10002],          # R-1: two of line 2
    ]
    pool = build_opponent_pool(rounds, LINE, LEVEL)
    assert pool == {1: 2, 2: 2}, pool   # line1: max(2,2,0)=2 (NOT summed); line2: max(1,1,2)=2
    print("pool rule OK:", pool)

    cards = sorted(opponent_pool_cards(rounds, LINE, LEVEL))
    # line1 rep = R-3's two lv1s [10001,10001] (2 copies, == R-2's single lv2); line2 rep = R-1's [10002,10002].
    assert cards == [10001, 10001, 10002, 10002], cards
    print("pool cards OK:", cards)

    opp = {"exp": 30, "extraMaxHp": 4}
    assert project_opponent(opp) == {"exp": 35, "extraMaxHp": 6}
    print("projection OK")

    # Rock-paper-scissors payoff: unique equilibrium = uniform 1/3, value 0.
    rps = [[0, -1, 1], [1, 0, -1], [-1, 1, 0]]
    row, col, val = solve_zero_sum(rps, iters=5000)
    assert all(abs(p - 1/3) < 0.03 for p in row), row
    assert abs(val) < 0.05, val
    print("RPS equilibrium OK:", [round(p, 3) for p in row], "value", round(val, 3))

    # Dominant-row game: row 0 always best -> probability ~1 on row 0.
    dom = [[2, 3, 2], [0, 1, 0], [-1, 0, -1]]
    row, _c, val = solve_zero_sum(dom, iters=2000)
    assert row[0] > 0.95, row
    print("dominant-row OK:", [round(p, 3) for p in row], "value", round(val, 3))

    # End-to-end with an injected evaluator (my board sum beats opp board sum).
    my_boards = [[10001], [20001], [10001, 10002]]
    opp_boards = [[10002], [10002, 10002]]
    ev = lambda mb, ob: sum(mb) - sum(ob)
    res = compute(my_boards, opp_boards, ev, rng=random.Random(0))
    print("top lines:", [(ln.board, round(ln.probability, 3)) for ln in res.top])
    print("pick:", res.pick.board if res.pick else None, "value:", round(res.value, 1))

    # Best-response guard: a TRAP row beats the seeded columns but loses to an
    # unseeded COUNTER. A fixed solve recommends the trap; the guard must find the
    # counter and switch to the safe row. (Mirrors the replay-study failure.)
    PAY = {
        ("A", "x"): 10, ("A", "y"): 10, ("A", "counter"): -20,   # trap: great vs seeds, dies to counter
        ("B", "x"): 1,  ("B", "y"): 1,  ("B", "counter"): 1,     # safe: mediocre but robust
    }
    ev2 = lambda mb, ob: PAY[(mb[0], ob[0])]
    my2 = [["A"], ["B"]]
    # Fixed solve WITHOUT the counter column -> recommends the trap A.
    fixed = compute(my2, [["x"], ["y"]], ev2)
    assert fixed.pick.board == ["A"], fixed.pick.board
    # Guarded solve: counter is in the candidate pool but NOT seeded -> must add it and pick B.
    guarded, opp_guard, cols, cache = solve_with_opponent_guard(
        my2, [["x"], ["y"]], [["x"], ["y"], ["counter"]], ev2, rng=random.Random(0))
    assert any(c[0] == "counter" for c in cols), cols
    assert guarded.pick.board == ["B"], guarded.pick.board
    # the opponent's predicted line should be the counter (it's what punishes A)
    assert opp_guard.pick.board == ["counter"], opp_guard.pick.board
    print(f"guard OK: fixed picks trap {fixed.pick.board}, guarded picks safe "
          f"{guarded.pick.board} after finding counter (cols={[c[0] for c in cols]})")
    print("ALL SELF-TESTS PASSED")
