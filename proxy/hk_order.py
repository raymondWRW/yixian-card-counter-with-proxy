# -*- coding: utf-8 -*-
"""hk_order.py — exact cyclic ordering via Held-Karp under learned adjacency weights.

The battle board is CYCLIC (slot 8 loops back to slot 1), so under a pairwise model
an ordering's value is the sum of directed adjacency weights w[a->b] around the ring.
Maximizing that over orders = max-weight Hamiltonian cycle = TSP; at n<=8 Held-Karp
solves it EXACTLY in O(n^2 * 2^n) (~16K ops, microseconds).

Weights come from learn_adjacency.py (season-9 replays): PMI of observed adjacency on
WINNING boards vs the random-cyclic-order null — controls for co-selection, isolates
order preference. Lookup is at LINE level (level stripped); unknown pairs are neutral
(0) so everything degrades gracefully.

Intended uses in the calculator:
  (a) order-aware RANKING key for candidate card SETS — best_cycle value approximates
      V*(S) (the set's value at its best order) without any combat sim, fixing the
      "ranked by one arbitrary order" flaw;
  (b) SEED order for the engine ordering search (hill-climb starts near-optimal).

NOT exact for real combat: long-accumulation effects (stacks built early, cashed
late) are not pairwise. The engine keeps the final say; this narrows where it looks.

API:
  available() -> bool
  best_cycle(cards)  -> (ordered_cards, value)          # one card-id list
  best_cycles(sets)  -> [(ordered_cards, value), ...]   # batched, groups by n
Card ids keep their level; weights are looked up by line. Rotation is arbitrary
(cycle value is rotation-invariant) — the engine picks the actual starting card.
"""
import os
import threading

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_NPZ = os.path.join(_HERE, "model", "adjacency.npz")

_lock = threading.Lock()
_state = None          # (W matrix, {line: index}) or False once probed


def _line_of(c):
    c = int(c)
    return c - ((c // 10000) % 100) * 10000


def _load():
    global _state
    with _lock:
        if _state is None:
            try:
                z = np.load(_NPZ)
                W = z["W"].astype(np.float32)
                idx = {int(v): i for i, v in enumerate(z["lines"])}
                _state = (W, idx)
            except Exception:
                _state = False
        return _state


def available() -> bool:
    return bool(_load())


def _weight_tensor(sets):
    """(B, n, n) adjacency weights for same-size card-id lists. Unknown lines -> 0."""
    st = _load()
    W, idx = st
    B, n = len(sets), len(sets[0])
    rows = np.full((B, n), -1, dtype=np.int64)
    for b, cards in enumerate(sets):
        for i, c in enumerate(cards):
            rows[b, i] = idx.get(_line_of(c), -1)
    Wb = np.zeros((B, n, n), dtype=np.float32)
    known = rows >= 0
    for b in range(B):
        ki = np.where(known[b])[0]
        if ki.size:
            sub = W[np.ix_(rows[b, ki], rows[b, ki])]
            Wb[b][np.ix_(ki, ki)] = sub
        np.fill_diagonal(Wb[b], 0.0)   # self-adjacency only occurs via duplicates
    return Wb


def _hk_batch(Wb):
    """Exact max-weight Hamiltonian CYCLE per batch item.

    Wb: (B, n, n). Returns orders (B, n) position indices and values (B,).
    Node 0 is fixed as the cycle start (rotation-invariant)."""
    B, n, _ = Wb.shape
    if n == 1:
        return np.zeros((B, 1), dtype=np.int64), np.zeros(B, dtype=np.float32)
    if n == 2:
        return (np.tile(np.array([0, 1]), (B, 1)),
                (Wb[:, 0, 1] + Wb[:, 1, 0]).astype(np.float32))
    FULL = 1 << n
    NEG = np.float32(-1e18)
    dp = np.full((FULL, B, n), NEG, dtype=np.float32)
    par = np.full((FULL, B, n), -1, dtype=np.int8)
    dp[1, :, 0] = 0.0
    nonmember = {S: np.array([k for k in range(n) if not (S >> k) & 1],
                             dtype=np.int64) for S in range(FULL)}
    for S in range(3, FULL, 2):            # subsets containing node 0
        for j in range(1, n):
            if not (S >> j) & 1:
                continue
            Sp = S ^ (1 << j)
            cand = dp[Sp] + Wb[:, :, j]    # (B, n): come from k, append j
            nm = nonmember[Sp]
            if nm.size:
                cand[:, nm] = NEG
            k = np.argmax(cand, axis=1)
            ar = np.arange(B)
            dp[S, :, j] = cand[ar, k]
            par[S, :, j] = k.astype(np.int8)
    close = dp[FULL - 1] + Wb[:, :, 0]     # wrap last -> node 0
    close[:, 0] = NEG
    jend = np.argmax(close, axis=1)
    vals = close[np.arange(B), jend].astype(np.float32)
    orders = np.zeros((B, n), dtype=np.int64)
    for b in range(B):
        S, j, seq = FULL - 1, int(jend[b]), []
        while j != 0:
            seq.append(j)
            pj = int(par[S, b, j])
            S ^= (1 << j)
            j = pj
        seq.append(0)
        orders[b] = seq[::-1]
    return orders, vals


def best_cycles(sets):
    """Batched exact cyclic ordering. sets: list of card-id lists (levels kept).
    Returns [(ordered_cards, value), ...] aligned with the input."""
    if not available():
        return [(list(s), 0.0) for s in sets]
    out = [None] * len(sets)
    by_n = {}
    for i, s in enumerate(sets):
        s = [c for c in s if c]
        if not s:
            out[i] = ([], 0.0)
            continue
        by_n.setdefault(len(s), []).append((i, s))
    for n, group in by_n.items():
        Wb = _weight_tensor([s for _, s in group])
        orders, vals = _hk_batch(Wb)
        for g, (i, s) in enumerate(group):
            out[i] = ([s[p] for p in orders[g]], float(vals[g]))
    return out


def best_cycle(cards):
    """Single-set convenience wrapper."""
    return best_cycles([cards])[0]


if __name__ == "__main__":
    # smoke: planted chain 0->1->...->7->0 must be recovered exactly (value = 8)
    n = 8
    W = np.zeros((1, n, n), dtype=np.float32)
    for i in range(n):
        W[0, i, (i + 1) % n] = 1.0
    orders, vals = _hk_batch(W)
    o = list(orders[0])
    ok = abs(vals[0] - n) < 1e-6 and all(
        o[(t + 1) % n] == (o[t] + 1) % n for t in range(n))
    print("planted-chain:", "OK" if ok else "FAIL", o, float(vals[0]))
    # noise + planted chain, batched, mixed sizes
    rng = np.random.default_rng(1)
    W2 = rng.normal(0, .1, (3, 6, 6)).astype(np.float32)
    for b in range(3):
        for i in range(6):
            W2[b, i, (i + 1) % 6] += 2.0
    o2, v2 = _hk_batch(W2)
    ok2 = all(all(o2[b][(t + 1) % 6] == (o2[b][t] + 1) % 6 for t in range(6))
              for b in range(3))
    print("noisy-chain batch:", "OK" if ok2 else "FAIL", v2)
    print("weights file:", "loaded" if available() else "MISSING (neutral mode)")
