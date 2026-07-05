# -*- coding: utf-8 -*-
"""How often does the SYSTEM's recommended line WIN, given only the opponent's past
rounds? Full pipeline: v3 model predicts the opponent's next board from their history,
the best-line search builds my counter from my available cards, and we score it against
the opponent's ACTUAL next board via the Oracle.

Perspective = the live use case. "Me" = a self-record player S (full features + the exact
cards they had that round); "opponent" = the player O they faced, predicted from O's
history/fates. Ground truth = O's actual next board. The BASELINE is the real combat that
happened: S's actual board vs O's actual board — i.e. what a strong (daoxin>=4000) human
chose. So the bar is "does the system beat what the human actually played?".

Win = positive 命 margin vs the real opponent. Usage: python test_winrate.py [n] [fast]
"""
import os, sys, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oracle_sim as O
import live_nash

SEQ = os.path.join(os.path.dirname(__file__), "..", "..", "yixian replay analysis",
                   "board_sequences.jsonl")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
FAST = len(sys.argv) > 2 and sys.argv[2] == "fast"
random.seed(0)


def score(me_fx, opp_fx, my_board, opp_board, rnd):
    mp = O._player(me_fx); op = live_nash.project_opponent(O._player(opp_fx))
    with O._lock:
        w = O._get_worker()
        r = w.run({"p1": {**mp, "usedCards": list(my_board)},
                   "p2": {**op, "usedCards": list(opp_board)},
                   "battleParams": [], "mainViewId": "", "round": rnd,
                   "expected": {}, "wantLog": False})
    return float(r.get("lifeDamage", 0) or 0) + float(r.get("hpDelta", 0) or 0) / 1000.0


# ---- sample rounds: real opponent, enough history, a real next board ----
samples = []
for line in open(SEQ, encoding="utf-8"):
    rec = json.loads(line); rs = rec["rounds"]
    for i in range(3, len(rs)):
        rnd = rs[i].get("round") or 0
        if not (8 <= rnd <= 16):
            continue
        cur, nxt = rs[i - 1], rs[i]
        if cur.get("opp_bot"):                       # only real opponents
            continue
        if not (nxt["board"] and cur["board"] and cur["opp_board"] and nxt["opp_board"]):
            continue
        samples.append((rec, i))
    if len(samples) > 40000:
        break
random.shuffle(samples); samples = samples[:N]
print(f"scoring {len(samples)} rounds | search={'fast' if FAST else 'final'}", flush=True)
if not O.available():
    sys.exit("no oracle")

mod_win = ora_win = hum_win = 0
msum = osum = hsum = 0.0
done = 0
# head-to-head: CALCULATOR (model) vs HUMAN, round by round
mc_resc = mc_break = both_w = both_l = 0     # calc-rescue / calc-break / both-win / both-lose
mc_better = mc_worse = mc_same = 0           # by 命 margin (calc - human)
for rec, i in samples:
    rs = rec["rounds"]
    B = lambda j: [int(c) for c in (rs[j]["board"] if 0 <= j < len(rs) else []) if c]
    Ob = lambda j: [int(c) for c in (rs[j]["opp_board"] if 0 <= j < len(rs) else []) if c]
    rnd = rs[i]["round"]
    real_opp = Ob(i)                                 # the opponent's ACTUAL next board
    human = B(i)                                     # what the strong player actually played
    # Available cards = the player's ACTUAL final cards (board[i]). Using board[i-1]+delta
    # double-counts merges (consumed lv1s + the lv2 result coexist — illegal). With board[i]
    # the search can reproduce the human's board exactly, so any loss is a real
    # anticipation/ordering miss, not a fabricated pool. Tests arrangement + best-response.
    my_cur = B(i); my_hand = []
    # me = the self-record player (full features + real cards)
    me = {"characterId": rec["char"], "career": rec.get("career") or 0,
          "level": rs[i]["realm"], "exp": 40, "extraMaxHp": 0, "unlockGrids": 8,
          "usedCards": my_cur, "talents": rs[i]["fates"], "fateStrategies": rs[i]["derivs"]}
    # opp = the faced player, predicted from THEIR history (+ their fates, on wire live)
    opp = {"characterId": rs[i - 1].get("opp_char") or rec["char"], "career": 0,
           "level": rs[i]["realm"], "exp": 40, "extraMaxHp": 0, "unlockGrids": 8,
           "usedCards": Ob(i - 1), "talents": rs[i - 1].get("opp_fates") or [],
           "fateStrategies": rs[i - 1].get("opp_derivs") or []}
    kw = dict(my_boards_by_round=[B(i - 3), B(i - 2), B(i - 1)],
              my_hand=my_hand, rnd=rnd, fast=FAST, top_k=1)
    rm = O.live_best_lines(me, opp, [Ob(i - 3), Ob(i - 2), Ob(i - 1)],
                           use_board_model=True, **kw)
    ro = O.live_best_lines(me, opp, [Ob(i - 3), Ob(i - 2), Ob(i - 1)],
                           use_board_model=False, **kw)
    if not rm or not rm.get("pick_board") or not ro or not ro.get("pick_board"):
        continue
    s_mod = score(me, opp, rm["pick_board"], real_opp, rnd)
    s_ora = score(me, opp, ro["pick_board"], real_opp, rnd)
    s_hum = score(me, opp, human, real_opp, rnd)
    msum += s_mod; osum += s_ora; hsum += s_hum
    win_m, win_h = s_mod > 0, s_hum > 0
    mod_win += win_m; ora_win += (s_ora > 0); hum_win += win_h
    both_w += (win_m and win_h); both_l += (not win_m and not win_h)
    mc_resc += (win_m and not win_h); mc_break += (win_h and not win_m)
    d = s_mod - s_hum
    mc_better += (d > 0.05); mc_worse += (d < -0.05); mc_same += (-0.05 <= d <= 0.05)
    done += 1
    if done % 20 == 0:
        print(f"[{done}] win% model {100*mod_win/done:.0f} oracle {100*ora_win/done:.0f} "
              f"human {100*hum_win/done:.0f} | avg命 model {msum/done:+.1f} oracle {osum/done:+.1f} "
              f"human {hsum/done:+.1f}", flush=True)

n = max(done, 1)
print(f"\n=== {done} rounds (opponent predicted from past 3 rounds, search={'fast' if FAST else 'final'}) ===")
print(f"{'method':<22}{'win rate':>10}{'avg 命':>10}")
print(f"{'SYSTEM (model)':<22}{100*mod_win/n:>9.0f}%{msum/n:>+10.2f}")
print(f"{'SYSTEM (oracle-solve)':<22}{100*ora_win/n:>9.0f}%{osum/n:>+10.2f}")
print(f"{'HUMAN (actual combat)':<22}{100*hum_win/n:>9.0f}%{hsum/n:>+10.2f}")
print(f"\n--- CALCULATOR (model) vs HUMAN, head-to-head over {done} rounds ---")
print(f"  win rate:   calc {100*mod_win/n:.0f}%   vs   human {100*hum_win/n:.0f}%")
print(f"  avg 命:     calc {msum/n:+.2f}   vs   human {hsum/n:+.2f}   (edge {(msum-hsum)/n:+.2f})")
print(f"  calc WINS a round the human LOST (rescue): {mc_resc}")
print(f"  human WINS a round the calc LOST (break):  {mc_break}   -> net {mc_resc - mc_break:+d}")
print(f"  same outcome: both win {both_w} | both lose {both_l}")
print(f"  by 命 margin: calc better {mc_better} | worse {mc_worse} | tie {mc_same}")
print("DONE", flush=True)
