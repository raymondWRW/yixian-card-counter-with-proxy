# -*- coding: utf-8 -*-
"""FAST vs FINAL pass quality on the corrected v2 harness — is the ~3s line good
enough, or does waiting for the deep pass matter?

Per round, run the LIVE arm twice (fast=True / fast=False), score both picks
against the opponent's TRUE fought board, and compare head-to-head.

Usage: python test_fastfinal.py [n_games] [skip]
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_mygames as T
import oracle_sim as O


def main():
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    skip = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    games = T.load_games(n_games, skip)
    print(f"fast-vs-final: {len(games)} games (skip {skip})", flush=True)
    if not O.available():
        sys.exit("no oracle")

    n = f_win = d_win = 0
    fsum = dsum = 0.0
    f_time = d_time = 0.0
    d_better = f_better = same_pick = 0
    flip = 0                                  # rounds where final wins and fast loses

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
                      top_k=1, use_board_model=True)
            t0 = time.time()
            rf = O.live_best_lines(me_fx, opp_fx, visible, fast=True, **kw)
            t1 = time.time()
            rd = O.live_best_lines(me_fx, opp_fx, visible, fast=False, **kw)
            t2 = time.time()
            if not (rf and rf.get("pick_board") and rd and rd.get("pick_board")):
                continue
            s_f = T.score(me_fx, opp_fx, rf["pick_board"], target, rn)
            s_d = T.score(me_fx, opp_fx, rd["pick_board"], target, rn)
            n += 1
            fsum += s_f; dsum += s_d
            f_win += (s_f > 0); d_win += (s_d > 0)
            f_time += (t1 - t0); d_time += (t2 - t1)
            if tuple(rf["pick_board"]) == tuple(rd["pick_board"]):
                same_pick += 1
            if s_d > s_f + 0.05:
                d_better += 1
            elif s_f > s_d + 0.05:
                f_better += 1
            flip += (s_d > 0 and s_f <= 0)
            if n % 15 == 0:
                print(f"[{n}] FAST {100*f_win/n:.0f}%/{fsum/n:+.1f} ({f_time/n:.1f}s)  "
                      f"FINAL {100*d_win/n:.0f}%/{dsum/n:+.1f} ({d_time/n:.1f}s)",
                      flush=True)

    m = max(n, 1)
    print(f"\n=== FAST vs FINAL over {n} rounds (true fought boards) ===")
    print(f"FAST : {100*f_win/m:.0f}%  {fsum/m:+.2f}命   avg {f_time/m:.1f}s")
    print(f"FINAL: {100*d_win/m:.0f}%  {dsum/m:+.2f}命   avg {d_time/m:.1f}s")
    print(f"same pick: {same_pick}/{n} ({100*same_pick/m:.0f}%)")
    print(f"by 命: final better {d_better} | fast better {f_better} | ~equal {n-d_better-f_better}")
    print(f"rounds where WAITING for final flips a loss to a win: {flip} ({100*flip/m:.0f}%)")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
