#!/usr/bin/env python3
"""
board_search.py — post-game brute-force board search (the driver for the whole perf effort).

Given a recorded battle (fixture with `stat`) and a POOL of candidate cards (the ~16 a player held across
hand+deck), enumerate candidate boards (an ordered selection of `slots` cards) against the FIXED opponent,
simulate each via the parallel warm Oracle pool, and return the board that maximizes the player's destiny
delta (or minimizes destiny taken when no winning board exists). The search space is ~exponential-by-slots,
so this exists to (a) prove the use case and (b) measure how many boards/sec we can evaluate.

Deck variation is applied to a deep copy of the fixture's stat (override p<side>.publicData.lastRoundData.
usedCards) — the opponent side is untouched, so we measure exactly the post-game "what board should they
have played" question. Evaluation runs through oracle_pool.run_batch (N process-isolated warm workers).

Usage:
  uv run python tools/game-oracle/scripts/board_search.py [--fixture <path>] [--slots 8] [--workers 8]
                                                          [--samples 5000] [--side p1] [--version V]
"""
from __future__ import annotations

import argparse
import copy
import glob
import itertools
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
from oracle_pool import run_board_batch  # noqa: E402


def _first_fixture_with_stat() -> dict:
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "fixtures", "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if d.get("stat"):
            return d
    sys.exit("no fixture with a `stat` found in data/fixtures/")


def _used_cards(stat: dict, side: str) -> list[int]:
    try:
        return list(stat[side]["publicData"]["lastRoundData"]["usedCards"])
    except (KeyError, TypeError):
        return []


def _set_used_cards(stat: dict, side: str, cards: list[int]) -> None:
    stat[side]["publicData"]["lastRoundData"]["usedCards"] = list(cards)


def _candidate_boards(pool: list[int], slots: int, samples: int) -> list[list[int]]:
    """Ordered selections of `slots` cards from `pool`. Full enumeration if small, else random sample."""
    pool = list(dict.fromkeys(pool))  # unique, order-preserving
    if slots > len(pool):
        slots = len(pool)
    # full count of ordered selections = P(len, slots); enumerate if tractable, else sample
    full = 1
    for k in range(len(pool), len(pool) - slots, -1):
        full *= k
        if full > samples * 4:
            break
    if full <= samples:
        return [list(p) for p in itertools.permutations(pool, slots)]
    seen, boards = set(), []
    while len(boards) < samples:
        b = random.sample(pool, slots)  # random ordered selection
        key = tuple(b)
        if key in seen:
            continue
        seen.add(key)
        boards.append(b)
    return boards


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture", default=None, help="base fixture json (default: first with a stat)")
    ap.add_argument("--side", default="p1", choices=["p1", "p2"], help="which side's board to optimize")
    ap.add_argument("--slots", type=int, default=8, help="cards placed on the board")
    ap.add_argument("--pool", default=None, help="comma card ids the player held (default: the side's own deck)")
    ap.add_argument("--samples", type=int, default=5000, help="max boards to evaluate (cap on the search)")
    ap.add_argument("--workers", type=int, default=None, help="default: auto-scale to workload + cores")
    ap.add_argument("--chunk", type=int, default=1000, help="boards per in-process batch message")
    ap.add_argument("--version", default="001.0007.0000")
    ap.add_argument("--seed", type=int, default=12345)
    args = ap.parse_args()
    random.seed(args.seed)

    base = json.load(open(args.fixture, encoding="utf-8")) if args.fixture else _first_fixture_with_stat()
    stat = base["stat"]
    own = _used_cards(stat, args.side)
    pool = [int(x) for x in args.pool.split(",")] if args.pool else own
    if not pool:
        sys.exit(f"no card pool (side {args.side} has no usedCards and --pool not given)")

    boards = _candidate_boards(pool, args.slots, args.samples)
    # Auto-scale workers to the workload: each worker pays a ~900ms cold-start, so it needs enough boards
    # (~1200) to amortize. Cap at cores-8 (the measured sweet spot was ~24 on a 32-core box; beyond that
    # the single Python process's GIL managing the pipes, and core oversubscription, cost more than they add).
    if args.workers is not None:
        workers = args.workers
    else:
        cores = os.cpu_count() or 8
        cap = max(4, cores - 8)                       # ~24 on a 32-core box (measured sweet spot)
        workers = min(cap, max(min(12, cap), len(boards) // 1500))   # floor ~12 so small searches aren't starved
    print(f"=== board search: side={args.side} slots={args.slots} pool={len(pool)} cards, "
          f"{len(boards)} boards, {workers} workers, chunk {args.chunk}, v{args.version} ===")

    # In-process batch: prime each worker once, then evaluate boards in chunks fully in-process on the
    # cached br (one IPC round-trip per chunk, not per board).
    base_fixture = {"id": base.get("id") or "boardsearch", "stat": stat}
    t0 = time.time()
    results = run_board_batch(base_fixture, boards, n_workers=workers, version=args.version,
                              side=args.side, chunk=args.chunk)
    dt = time.time() - t0

    # Score: destiny delta in the side's favor. hpDelta is (left - right); flip if the side is on the right.
    # (Wire the true destiny/lifeDamage field once confirmed; hpDelta is the working proxy.)
    def score(hp: int) -> int:
        return hp if args.side == "p1" else -hp

    scored = [(score(r[0]), boards[i], r[1]) for i, r in enumerate(results) if r is not None]
    scored.sort(key=lambda x: x[0], reverse=True)
    n = len(scored)
    print(f"  evaluated {n} boards in {dt:.2f}s  =>  {n/dt:.0f} boards/s  ({workers} workers)")
    if scored:
        best = scored[0]
        print(f"  BEST score={best[0]:+d}  board={best[1]}  (turns={best[2]})")
        worst = scored[-1]
        print(f"  worst score={worst[0]:+d}  spread over {n} boards: {worst[0]:+d} .. {best[0]:+d}")


if __name__ == "__main__":
    main()
