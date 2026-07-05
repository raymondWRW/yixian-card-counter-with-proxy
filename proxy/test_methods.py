# -*- coding: utf-8 -*-
"""Head-to-head: does the ML board-model or the brute-force Oracle game-solve produce
BETTER live "best lines"? Both differ only in stage-1 (opponent prediction); stage-2
(my best response) is identical. For each replay round we know the opponent's ACTUAL
next board, so we score each method's recommended board against that real opponent via
the Oracle. Higher margin vs the real opponent = the better line.

Perspective: the SUBJECT (whom the model was trained to predict) is the OPPONENT here.
Their real next board = ground truth. "My" side = who the subject faced; both methods get
identical my-cards (current board + the cards I actually had next round as 'hand'), so the
only difference is the opponent prediction feeding the best response.

Usage: python test_methods.py [n_rounds]     (needs ORACLE_HOME/ORACLE_EXE)
"""
import os, sys, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oracle_sim as O
import live_nash
import board_model

SEQ = os.path.join(os.path.dirname(__file__), "..", "..", "yixian replay analysis",
                   "board_sequences.jsonl")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
random.seed(0)


_score_cache = {}


def score(me_fx, opp_fx, my_board, opp_board, rnd):
    """My combat margin (命 + hp tiebreak) for my_board vs opp_board."""
    key = (tuple(my_board), tuple(opp_board), rnd)
    v = _score_cache.get(key)
    if v is not None:
        return v
    mp = O._player(me_fx)
    op = live_nash.project_opponent(O._player(opp_fx))   # +1 round growth, as live calc
    with O._lock:
        w = O._get_worker()
        r = w.run({"p1": {**mp, "usedCards": list(my_board)},
                   "p2": {**op, "usedCards": list(opp_board)},
                   "battleParams": [], "mainViewId": "", "round": rnd,
                   "expected": {}, "wantLog": False})
    v = float(r.get("lifeDamage", 0) or 0) + float(r.get("hpDelta", 0) or 0) / 1000.0
    _score_cache[key] = v
    return v


def model_gen_pick(me, opp, opp_mix, gen_feats, available, rnd):
    """Model GENERATES my candidate boards (constrained to my cards), then Oracle
    best-responds to the predicted opponent mix. Returns the chosen board or None."""
    cands = board_model.get_predictor().generate_board(available=available, top_k=6, **gen_feats)
    if not cands:
        return None
    best, bestv = None, -1e9
    for cb, _ in cands:
        exp = sum(w * score(me, opp, cb, ob, rnd) for ob, w in opp_mix)
        if exp > bestv:
            bestv, best = exp, cb
    return best


# ---- gather candidate rounds (need history + a real next board) ----
samples = []
for line in open(SEQ, encoding="utf-8"):
    rec = json.loads(line); rs = rec["rounds"]
    for i in range(3, len(rs)):
        rnd = rs[i].get("round") or 0
        if not (8 <= rnd <= 16):
            continue
        if not (rs[i]["board"] and rs[i - 1]["board"] and rs[i - 1]["opp_board"]
                and rs[i]["opp_board"]):
            continue
        samples.append((rec, i))
    if len(samples) > 40000:
        break
random.shuffle(samples); samples = samples[:N]
print(f"scoring {len(samples)} rounds (model vs brute-force, vs real opponent)", flush=True)

if not O.available():
    sys.exit("no oracle")

# three methods, all producing MY board, scored vs the opponent's REAL next board:
#   brute    = Oracle game-solve opponent + brute-enumerated my candidates
#   model    = model opponent prediction + brute-enumerated my candidates
#   gen      = model opponent prediction + MODEL-GENERATED my candidates (my cards only)
S = {k: 0.0 for k in ("brute", "model", "gen")}       # summed 命 margin
beats = {k: 0 for k in S}                              # pick beats real opp (命>0)
best_of = {k: 0 for k in S}                            # strictly-best of the three
done = 0
for rec, i in samples:
    rs = rec["rounds"]
    B = lambda j: [int(c) for c in (rs[j]["board"] if 0 <= j < len(rs) else []) if c]
    Ob = lambda j: [int(c) for c in (rs[j]["opp_board"] if 0 <= j < len(rs) else []) if c]
    rnd = rs[i]["round"]
    real_opp = B(i)                                  # the subject's ACTUAL next board
    my_cur = Ob(i - 1)
    my_hand = [c for c in Ob(i) if c not in my_cur]
    me = {"characterId": rs[i - 1].get("opp_char") or rec["char"], "career": 0,
          "level": rs[i]["realm"], "exp": 40, "extraMaxHp": 0, "unlockGrids": 8,
          "usedCards": my_cur}
    opp = {"characterId": rec["char"], "career": rec.get("career") or 0,
           "level": rs[i]["realm"], "exp": 40, "extraMaxHp": 0, "unlockGrids": 8,
           "usedCards": B(i - 1), "talents": rs[i]["fates"], "fateStrategies": rs[i]["derivs"]}
    opp_hist = [B(i - 3), B(i - 2), B(i - 1)]
    my_hist = [Ob(i - 3), Ob(i - 2), Ob(i - 1)]
    kw = dict(my_boards_by_round=my_hist, my_hand=my_hand, rnd=rnd, fast=True, top_k=3)
    rmodel = O.live_best_lines(me, opp, opp_hist, use_board_model=True, **kw)
    rbrute = O.live_best_lines(me, opp, opp_hist, use_board_model=False, **kw)
    if not rmodel or not rbrute or not rmodel.get("pick_board") or not rbrute.get("pick_board"):
        continue
    # opponent mix from the MODEL prediction (reused for the gen best-response)
    opp_mix = [(l["board"], l["probability"]) for l in (rmodel.get("opp_lines") or []) if l.get("board")]
    tot = sum(w for _, w in opp_mix) or 1.0
    opp_mix = [(b, w / tot) for b, w in opp_mix] or [(rmodel["opp_pick_board"] or B(i - 1), 1.0)]
    gen_feats = dict(char=me["characterId"], career=0, realm=me["level"], rnd=rnd,
                     cur_board=my_cur, opp_board=B(i - 1), fates=[], derivs=[],
                     own_hist=(Ob(i - 2), Ob(i - 3)), opp_hist=(B(i - 2), B(i - 3)))
    pgen = model_gen_pick(me, opp, opp_mix, gen_feats, my_cur + my_hand, rnd)

    picks = {"brute": rbrute["pick_board"], "model": rmodel["pick_board"], "gen": pgen}
    sc = {}
    for k, pb in picks.items():
        if pb is None:
            sc[k] = None; continue
        v = score(me, opp, pb, real_opp, rnd)
        sc[k] = v; S[k] += v; beats[k] += (v > 0)
    valid = {k: v for k, v in sc.items() if v is not None}
    if valid:
        bestk = max(valid, key=valid.get); best_of[bestk] += 1
    done += 1
    if done % 20 == 0:
        print(f"[{done}] avg命 brute {S['brute']/done:+.2f} model {S['model']/done:+.2f} "
              f"gen {S['gen']/done:+.2f} | best-of-3 {dict(best_of)}", flush=True)

print(f"\n=== {done} rounds scored vs REAL opponent ===")
print(f"{'method':<8}{'avg 命 margin':>14}{'beats opp':>12}{'best of the 3':>15}")
for k in ("brute", "model", "gen"):
    print(f"{k:<8}{S[k]/max(done,1):>+14.2f}{100*beats[k]/max(done,1):>11.0f}%"
          f"{best_of[k]:>12} ({100*best_of[k]/max(done,1):.0f}%)")
print("DONE", flush=True)
