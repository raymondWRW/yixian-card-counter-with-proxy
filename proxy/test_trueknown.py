# -*- coding: utf-8 -*-
"""TRUE-known benchmark: the opponent's EXACT board is given (no prediction at all)
— the calc best-responds to that single board from my full pool (board + hand).
Upper bound of live strength = pure selection + ordering power. Compare to HUMAN
(what I actually played) scored vs the same real board.

Usage: python test_trueknown.py [n_games] [skip]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_mygames as T
import oracle_sim as O


def main():
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    skip = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    games = T.load_games(n_games, skip)
    print(f"TRUE-known: {len(games)} games (skip {skip})", flush=True)
    if not O.available():
        sys.exit("no oracle")
    c_win = h_win = 0
    csum = hsum = 0.0
    n = 0
    resc = brk = 0
    for folder, my_char, career, states in games:
        rounds = sorted(states)
        mbr = {rn: T.board_ids_of(states[rn].get("me")) for rn in rounds}
        opp_hist = {}
        for rn in rounds:
            op = states[rn].get("opponent") or {}
            oid = op.get("player_id")
            ob = T.board_ids_of(op)
            if oid and ob:
                opp_hist.setdefault(oid, {})[rn] = ob
        for rn in rounds:
            if rn < 4 or rn > 19:
                continue
            built = T.build_round(states, my_char, career, mbr, opp_hist, rn)
            if not built:
                continue
            me_fx, opp_fx, my_hand, opp_actual, _prior, my_hist = built
            # EXACT board known: model OFF, opponent candidates capped to their
            # actual board only -> a pure best-response to one fixed board.
            r = O.live_best_lines(me_fx, opp_fx, [opp_actual],
                                  my_boards_by_round=my_hist, my_hand=my_hand,
                                  rnd=rn, fast=False, top_k=1,
                                  use_board_model=False, opp_max_boards=1)
            if not r or not r.get("pick_board"):
                continue
            s_c = T.score(me_fx, opp_fx, r["pick_board"], opp_actual, rn)
            s_h = T.score(me_fx, opp_fx, me_fx["usedCards"], opp_actual, rn)
            csum += s_c; hsum += s_h
            c_win += (s_c > 0); h_win += (s_h > 0)
            resc += (s_c > 0 and s_h <= 0); brk += (s_h > 0 and s_c <= 0)
            n += 1
            if n % 15 == 0:
                print(f"[{n}] CALC {100*c_win/n:.0f}%/{csum/n:+.1f} "
                      f"HUMAN {100*h_win/n:.0f}%/{hsum/n:+.1f}", flush=True)
    m = max(n, 1)
    print(f"\n=== TRUE-known over {n} rounds ===")
    print(f"CALC (exact board given): {100*c_win/m:.0f}%  {csum/m:+.2f}命")
    print(f"HUMAN (actual play):      {100*h_win/m:.0f}%  {hsum/m:+.2f}命")
    print(f"rescues {resc} / breaks {brk}  (net {resc-brk:+d})")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
