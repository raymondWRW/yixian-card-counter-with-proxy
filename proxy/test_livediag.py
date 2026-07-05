# -*- coding: utf-8 -*-
"""LOSS ANATOMY of the live calculator, on the corrected v2 harness.

For every round, run the LIVE arm (model prediction from live-visible history) and
the TRUE arm (exact fought board given), score both against the TRUE board, then
classify each LIVE loss:

  UNWINNABLE   TRUE also lost — no arrangement of my pool beats that board (or
               the search/sim can't find/see it). Not a prediction problem.
  PRED MISS    TRUE won, and the true board's card-LINE multiset was NOT among
               the predicted candidates — the model never saw it coming.
  SOFT HEDGE   TRUE won, and the true board WAS in the predicted support — the
               information was there, but best-responding to the hedged mix
               chose a board that loses to the real one.

Also reports calibration: the calc's own pick_winrate vs realized outcomes.

Usage: python test_livediag.py [n_games] [skip] [--fast]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_mygames as T
import oracle_sim as O


def line_key(board):
    return tuple(sorted(O._line_of(c) for c in board if c))


def main():
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    skip = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    fast = "--fast" in sys.argv
    games = T.load_games(n_games, skip)
    print(f"loss-anatomy: {len(games)} games (skip {skip}) | "
          f"search={'fast' if fast else 'final'}", flush=True)
    if not O.available():
        sys.exit("no oracle")

    n = l_win = 0
    unwin = miss = soft = 0
    miss_probs = []          # predicted prob mass on the true set when present
    cal = []                 # (pick_winrate, realized 0/1)
    hum_win = true_win = 0

    for folder, my_char, career, states, rec in games:
        opp_hist = {}
        for rn in sorted(states):
            op = states[rn].get("opponent") or {}
            oid = op.get("player_id")
            ob = T.board_ids_of(op)
            if oid and ob:
                opp_hist.setdefault(oid, {})[rn] = ob
        for rn in sorted(states):
            if rn < 4 or rn > 19:
                continue
            built = T.build_round(states, my_char, career, opp_hist, rec, rn)
            if not built:
                continue
            me_fx, opp_fx, pool_hand, target, visible, my_hist, human = built
            if not visible:
                continue
            kw = dict(my_boards_by_round=my_hist, my_hand=pool_hand, rnd=rn,
                      fast=fast)
            rl = O.live_best_lines(me_fx, opp_fx, visible,
                                   use_board_model=True, top_k=8, **kw)
            rt = O.live_best_lines(me_fx, opp_fx, [target],
                                   use_board_model=False, opp_max_boards=1,
                                   top_k=1, **kw)
            if not (rl and rl.get("pick_board") and rt and rt.get("pick_board")):
                continue
            s_h = T.score(me_fx, opp_fx, human, target, rn)
            s_l = T.score(me_fx, opp_fx, rl["pick_board"], target, rn)
            s_t = T.score(me_fx, opp_fx, rt["pick_board"], target, rn)
            n += 1
            hum_win += (s_h > 0); true_win += (s_t > 0)
            cal.append((float(rl.get("pick_winrate") or 0.0), 1.0 if s_l > 0 else 0.0))
            if s_l > 0:
                l_win += 1
                continue
            # ---- LIVE lost: classify ----
            if s_t <= 0:
                unwin += 1
                continue
            tk = line_key(target)
            cand_sets = {line_key(b) for b in (rl.get("opp_active_boards") or [])}
            if tk not in cand_sets:
                miss += 1
            else:
                soft += 1
                p = 0.0
                for ln in (rl.get("opp_lines") or []):
                    if line_key(ln.get("board") or []) == tk:
                        p = max(p, float(ln.get("probability") or 0.0))
                miss_probs.append(p)
            if n % 15 == 0:
                pass
            print(f"[{n}] r{rn} LIVE loss {s_l:+.1f} | TRUE {s_t:+.1f} -> "
                  f"{'unwinnable' if s_t <= 0 else ('pred-miss' if tk not in cand_sets else 'soft-hedge')}",
                  flush=True)

    m = max(n, 1)
    losses = max(n - l_win, 1)
    print(f"\n=== loss anatomy over {n} rounds "
          f"(search={'fast' if fast else 'final'}) ===")
    print(f"LIVE wins {l_win}/{n} ({100*l_win/m:.0f}%)   "
          f"[human {100*hum_win/m:.0f}%, true-known {100*true_win/m:.0f}%]")
    print(f"LIVE losses: {n - l_win}")
    print(f"  UNWINNABLE (true-known also lost): {unwin}  ({100*unwin/losses:.0f}% of losses)")
    print(f"  PRED MISS  (true board not predicted): {miss}  ({100*miss/losses:.0f}%)")
    print(f"  SOFT HEDGE (predicted but out-hedged): {soft}  ({100*soft/losses:.0f}%)")
    if miss_probs:
        print(f"    soft-hedge: avg predicted prob on the true set "
              f"{sum(miss_probs)/len(miss_probs):.2f}")
    # calibration: expected vs realized, in confidence buckets
    buckets = {}
    for p, w in cal:
        b = min(9, int(p * 10))
        buckets.setdefault(b, []).append((p, w))
    print("calibration (calc pick_winrate -> realized):")
    for b in sorted(buckets):
        xs = buckets[b]
        print(f"  {b/10:.1f}-{(b+1)/10:.1f}: expected {sum(p for p,_ in xs)/len(xs):.2f} "
              f"realized {sum(w for _,w in xs)/len(xs):.2f}  (n={len(xs)})")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
