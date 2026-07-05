# -*- coding: utf-8 -*-
"""test_hk_order.py — MAKE-OR-BREAK for the Held-Karp ordering design.

Question: how close does the pairwise-TSP (Held-Karp) order get to the engine's
TRUE best order of the same cards? If it lands within ~1 命 of best on most boards,
the learned-adjacency + HK design is validated as a ranking key / seed. If not, we
need richer DP state or engine-transition search.

Protocol, per sampled round (TEST split, real opponents, the same fixture style as
test_winrate): freeze MY card multiset (the player's actual board) and the OPPONENT's
actual board; only MY ordering varies. Engine margin = lifeDamage + hpDelta/1000.
  ACTUAL   the order the strong player really used
  RANDOM   mean/max of R random shuffles (how much does order matter here at all?)
  HK       Held-Karp cycle from learned weights; all n rotations tried, best kept
           (cycle is rotation-invariant, the opening isn't)
  BEST     strongest order found by exhaustive local search (swap + insertion moves,
           run to convergence) from seeds: ACTUAL, HK, random restarts — shared cache
  EXACT    optional: full n! enumeration on the first K boards to certify that BEST
           really is the optimum (calibrates the local search)

Usage: python test_hk_order.py [n_rounds] [exact_k]
"""
import os
import sys
import json
import random
import itertools

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oracle_sim as O
import live_nash
import hk_order

SEQ = os.path.join(os.path.dirname(__file__), "..", "..",
                   "yixian replay analysis", "board_sequences.jsonl")
N_ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
EXACT_K = int(sys.argv[2]) if len(sys.argv) > 2 else 0
R_RANDOM = 12
random.seed(0)

if not hk_order.available():
    sys.exit("adjacency.npz missing — run learn_adjacency.py first")
if not O.available():
    sys.exit("no oracle")

# ---- sample rounds from the TEST split (weights were learned on train only) ----
is_test = np.random.default_rng(0).random(200000) < 0.10
samples = []
for li, line in enumerate(open(SEQ, encoding="utf-8")):
    if not is_test[li]:
        continue
    rec = json.loads(line)
    rs = rec["rounds"]
    for i in range(1, len(rs)):
        r = rs[i]
        rnd = r.get("round") or 0
        if not (8 <= rnd <= 16) or r.get("opp_bot"):
            continue
        board = [int(c) for c in (r.get("board") or []) if c]
        ob = [int(c) for c in (r.get("opp_board") or []) if c]
        if len(board) < 7 or len(ob) < 6:
            continue
        samples.append((rec, i))
    if len(samples) > 8000:
        break
random.shuffle(samples)
samples = samples[:N_ROUNDS]
print(f"rounds: {len(samples)} | random shuffles: {R_RANDOM} | exact on first {EXACT_K}",
      flush=True)


def fixtures(rec, i):
    rs = rec["rounds"]
    r = rs[i]
    me = {"characterId": rec["char"], "career": rec.get("career") or 0,
          "level": r["realm"], "exp": 40, "extraMaxHp": 0, "unlockGrids": 8,
          "usedCards": [int(c) for c in r["board"] if c],
          "talents": r.get("fates") or [], "fateStrategies": r.get("derivs") or []}
    opp = {"characterId": r.get("opp_char") or rec["char"], "career": 0,
           "level": r["realm"], "exp": 40, "extraMaxHp": 0, "unlockGrids": 8,
           "usedCards": [int(c) for c in r["opp_board"] if c],
           "talents": r.get("opp_fates") or [], "fateStrategies": r.get("opp_derivs") or []}
    return me, opp


def local_search(start, ev):
    """Best-improvement local search over swaps + insertions, to convergence."""
    cur = list(start)
    cv = ev(cur)
    n = len(cur)
    improved = True
    while improved:
        improved = False
        for i in range(n):
            for j in range(i + 1, n):
                cand = cur[:]
                cand[i], cand[j] = cand[j], cand[i]
                v = ev(cand)
                if v > cv + 1e-9:
                    cur, cv, improved = cand, v, True
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                cand = cur[:]
                cand.insert(j, cand.pop(i))
                v = ev(cand)
                if v > cv + 1e-9:
                    cur, cv, improved = cand, v, True
    return cur, cv


rows = []
for bi, (rec, i) in enumerate(samples):
    me_fx, opp_fx = fixtures(rec, i)
    board = me_fx["usedCards"]
    ob = opp_fx["usedCards"]
    rnd = rec["rounds"][i]["round"]
    mp = O._player(me_fx)
    op = live_nash.project_opponent(O._player(opp_fx))
    cache = {}
    calls = [0]

    def ev(order):
        t = tuple(order)
        if t not in cache:
            with O._lock:
                w = O._get_worker()
                r = w.run({"p1": {**mp, "usedCards": list(order)},
                           "p2": {**op, "usedCards": list(ob)},
                           "battleParams": [], "mainViewId": "", "round": rnd,
                           "expected": {}, "wantLog": False})
            cache[t] = (float(r.get("lifeDamage", 0) or 0)
                        + float(r.get("hpDelta", 0) or 0) / 1000.0)
            calls[0] += 1
        return cache[t]

    s_act = ev(board)
    rands = []
    for _ in range(R_RANDOM):
        sh = board[:]
        random.shuffle(sh)
        rands.append(ev(sh))
    hk_cycle, hk_val = hk_order.best_cycle(board)
    rots = [hk_cycle[k:] + hk_cycle[:k] for k in range(len(hk_cycle))]
    s_hk0 = ev(hk_cycle)
    s_hk = max(ev(r) for r in rots)

    # BEST: local search from actual, HK-best-rotation, and random restarts
    seeds = [board, max(rots, key=ev)]
    for _ in range(4):
        sh = board[:]
        random.shuffle(sh)
        seeds.append(sh)
    s_best = max(local_search(s, ev)[1] for s in seeds)

    s_exact = None
    if bi < EXACT_K:
        best = -1e18
        for perm in itertools.permutations(board):
            v = ev(list(perm))
            if v > best:
                best = v
        s_exact = best

    rows.append(dict(n=len(board), act=s_act, rmean=float(np.mean(rands)),
                     rmax=float(np.max(rands)), hk0=s_hk0, hk=s_hk,
                     best=s_best, exact=s_exact, evals=calls[0]))
    ex = f" exact={s_exact:+.2f}" if s_exact is not None else ""
    print(f"[{bi+1}/{len(samples)}] n={len(board)} act={s_act:+.2f} "
          f"rand~{np.mean(rands):+.2f} hk={s_hk:+.2f} best={s_best:+.2f}{ex} "
          f"({calls[0]} evals)", flush=True)

# ---- aggregate ----
A = lambda k: np.array([r[k] for r in rows], dtype=float)
act, rmean, rmax, hk, best = A("act"), A("rmean"), A("rmax"), A("hk"), A("best")
spread = best - rmean
n = len(rows)
print(f"\n=== ordering quality over {n} rounds (fixed sets, engine margins) ===")
print(f"{'order':<22}{'avg 命':>9}{'avg gap to BEST':>17}{'within 1命 of best':>20}")
for name, v in (("BEST (local search)", best), ("HK (best rotation)", hk),
                ("ACTUAL (player)", act), ("RANDOM (mean)", rmean),
                ("RANDOM (max of 12)", rmax)):
    within = float(np.mean(best - v <= 1.0)) * 100
    print(f"{name:<22}{v.mean():>+9.2f}{(best - v).mean():>+17.2f}{within:>19.0f}%")
print(f"\nordering spread (BEST - random mean): avg {spread.mean():+.2f}, "
      f"max {spread.max():+.2f}  <- how much order matters on these boards")
print(f"HK beats/ties ACTUAL: {float(np.mean(hk >= act - 1e-9)) * 100:.0f}% of rounds")
wins_flip = float(np.mean((best > 0) & (act <= 0))) * 100
hk_flip = float(np.mean((hk > 0) & (act <= 0))) * 100
print(f"rounds where reordering alone flips a LOSS to a WIN: best {wins_flip:.0f}%, hk {hk_flip:.0f}%")
ex_rows = [r for r in rows if r["exact"] is not None]
if ex_rows:
    d = [r["exact"] - r["best"] for r in ex_rows]
    print(f"EXACT check on {len(ex_rows)} boards: exact - best = {d} "
          f"(0 == local search found the true optimum)")
print("DONE", flush=True)
