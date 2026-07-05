# -*- coding: utf-8 -*-
"""Calculator strength on MY OWN recorded games — CORRECTED harness.

v1 scored against the deck_tracker vm's opponent board, which turned out to be the
opponent's PREVIOUS-round board (67/101 exact matches to round N-1, only 12/101 to
the fought board): the counter — like the live player — only ever sees what the
opponent LAST fought with. v1's calc arms therefore optimized against the very
(stale) board they were scored on, inflating them.

v2 splits information correctly using the game's OWN record (recentBattleDatas,
verified bit-exact boards + real per-round stats for BOTH sides):

  TARGET  (scoring)   = opponent's TRUE fought board at round N (recent opp_cards)
  VISIBLE (prediction) = what live play actually shows: the opponent's boards from
                         rounds I previously faced them, freshest = their N-1 board
                         (the deck_tracker vm entry at round N)
  POOL    (my cards)   = my true fought board (recent me_cards) + my last-snapshot
                         hand (deck_tracker) — board+hand, the real available set
  STATS               = real per-round realm/xiuwei for both sides (recent stats)

Arms, all scored vs TARGET:
  HUMAN — my true fought board (what I actually played)
  LIVE  — calc with model prediction from VISIBLE history (live reality)
  TRUE  — calc given the exact TARGET board (no prediction; upper bound)

Also reports sign-agreement between the Oracle outcome of (HUMAN vs TARGET) and
the record's own `net` — a validity check of the reconstruction.

Usage: python test_mygames.py [n_games] [skip] [--fast]
"""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_archive as GA
import oracle_sim as O
import recent_battles as RB
import live_nash
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))

# ── name/level → wire card id, and fate/char maps ────────────────────────────
_cid = json.load(open(os.path.join(HERE, "card_id_map.json"), encoding="utf-8"))
def _norm(s): return re.sub(r"[·••\s]", "", s or "")
def _lvl(i): return ((i // 10000) % 100) + 1
ID_BY_NL = {}
for _k, _v in _cid.items():
    _i = int(_k); ID_BY_NL[(_norm(_v), _lvl(_i))] = _i
_fid = json.load(open(os.path.join(HERE, "fate_id_map.json"), encoding="utf-8"))
BASE_FATE = {}
for _k, _v in _fid.items():
    _i = int(_k); _n = _norm(_v)
    if _n not in BASE_FATE or _i < BASE_FATE[_n]:
        BASE_FATE[_n] = _i
_CM = json.load(open(os.path.join(HERE, "character_map.json"),
                    encoding="utf-8")).get("name_to_id", {})


def cards_to_ids(cards):
    out = []
    for c in cards or []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        i = c.get("id")
        if i:                                   # recent-record cards carry raw ids
            out.append(int(i))
            continue
        lv = int(c.get("level", 1) or 1)
        i = ID_BY_NL.get((_norm(c["name"]), lv))
        if i is None:
            b = ID_BY_NL.get((_norm(c["name"]), 1))
            if b is None:
                continue
            i = b + (lv - 1) * 10000
        out.append(i)
    return out


def fates_to_ids(names):
    out = []
    for nm in names or []:
        i = BASE_FATE.get(_norm(nm))
        if i:
            out.append(i)
    return out


def board_ids_of(vm_side):
    return cards_to_ids((vm_side or {}).get("board") or [])


def score(me_fx, opp_fx, my_board, opp_board, rnd):
    """命 margin of my_board vs opp_board on `rnd` (>0 = I win)."""
    mp = O._player(me_fx)
    op = live_nash.project_opponent(O._player(opp_fx), rnd=rnd)
    with O._lock:
        w = O._get_worker()
        r = w.run({"p1": {**mp, "usedCards": list(my_board)},
                   "p2": {**op, "usedCards": list(opp_board)},
                   "battleParams": [], "mainViewId": "", "round": rnd,
                   "expected": {}, "wantLog": False})
    return float(r.get("lifeDamage", 0) or 0) + float(r.get("hpDelta", 0) or 0) / 1000.0


def load_games(n_games, skip=0):
    """Counter folders matched to their recent-record rounds (by start time)."""
    recents = []
    try:
        for g in RB.decode_recent_games():
            try:
                _mn, _cid_, _pl, rounds = RB.game_rounds(g["start_local"])
                if rounds:
                    recents.append((g.get("ts_ms"), {rd["round"]: rd for rd in rounds}))
            except Exception:
                continue
    except Exception as e:
        sys.exit(f"recent decode failed: {e}")
    games, seen = [], 0
    for folder in sorted((Path(HERE).parent / "battle_log").glob("*/"), reverse=True):
        if not ((folder / "battle_log.json").exists()
                and (folder / "deck_tracker.jsonl").exists()):
            continue
        try:
            summ = GA._folder_game_summary(folder)
        except Exception:
            summ = None
        if not summ:
            continue
        my_char = _CM.get(summ.get("character"))
        if not my_char:
            continue
        states = GA.extract_round_states(folder)
        if len(states) < 8:
            continue
        epoch = GA._folder_epoch(folder.name)
        rec = None
        if epoch is not None:
            best = 151_000
            for ts_ms, byround in recents:
                if isinstance(ts_ms, int) and abs(ts_ms - epoch * 1000) < best:
                    best = abs(ts_ms - epoch * 1000)
                    rec = byround
        if not rec:
            continue                              # no bit-exact record — skip game
        seen += 1
        if seen <= skip:
            continue
        games.append((folder, int(my_char), summ.get("career_id") or 0, states, rec))
        if len(games) >= n_games:
            break
    return games


def build_round(states, my_char, career, opp_hist, rec, rn):
    """Returns (me_fx, opp_fx, pool_hand, target_opp, visible_hist, my_hist, human)
    or None. All boards are id lists; fixtures carry REAL per-round stats."""
    vm = states.get(rn)
    rd = rec.get(rn)
    if not vm or not rd:
        return None
    me = vm.get("me") or {}
    op = vm.get("opponent") or {}
    human = cards_to_ids(rd.get("me_cards"))          # my TRUE fought board
    target = cards_to_ids(rd.get("opp_cards"))        # opponent's TRUE fought board
    if not human or not target:
        return None
    ms, os_ = rd.get("me_stats") or {}, rd.get("opp_stats") or {}

    def _extra_hp(stats, realm):
        base = RB._REALM_BASE_HP.get(realm)
        mh = stats.get("max_hp")
        if isinstance(mh, int) and isinstance(base, int):
            return max(0, mh - base)
        return 0

    me_realm = ms.get("realm") or me.get("realm_tier") or 1
    opp_realm = os_.get("realm") or me_realm
    me_fx = {"characterId": my_char, "career": career,
             "level": me_realm,
             "exp": ms.get("xiuwei") or me.get("xiuwei") or 0,
             "extraMaxHp": _extra_hp(ms, me_realm),
             "unlockGrids": ms.get("unlocked") or 8,
             "usedCards": human, "talents": fates_to_ids(me.get("fateNames")),
             "fateStrategies": [int(x) for x in (me.get("derivations") or []) if x]}
    opp_fx = {"characterId": int(rd.get("opp_char_id") or my_char), "career": 0,
              "level": opp_realm,
              "exp": os_.get("xiuwei") or me_fx["exp"],
              "extraMaxHp": _extra_hp(os_, opp_realm),
              "unlockGrids": os_.get("unlocked") or 8,
              "usedCards": target,
              "talents": fates_to_ids(op.get("fateNames")), "fateStrategies": []}
    # my pool = true board + last-snapshot hand (the real available set)
    pool_hand = cards_to_ids(me.get("hand") or [])
    # VISIBLE history = live reality: boards from rounds I faced them, and the vm
    # entry AT rn (their round-(rn-1) board — what the matchup preview shows).
    oid = op.get("player_id")
    vis_rounds = sorted(r for r in opp_hist.get(oid, {}) if r <= rn)
    visible = [opp_hist[oid][r] for r in vis_rounds][-3:]
    my_hist = [board_ids_of((states.get(rn - k) or {}).get("me")) for k in (3, 2, 1)]
    return me_fx, opp_fx, pool_hand, target, visible, my_hist, human


def main():
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    skip = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    fast = "--fast" in sys.argv
    games = load_games(n_games, skip)
    print(f"games matched to records: {len(games)} (skip {skip}) | "
          f"search={'fast' if fast else 'final'}", flush=True)
    if not O.available():
        sys.exit("no oracle")

    h_win = l_win = t_win = 0
    hsum = lsum = tsum = 0.0
    n = agree = 0
    l_resc = l_break = t_resc = t_break = 0

    for folder, my_char, career, states, rec in games:
        opp_hist = {}
        for rn in sorted(states):
            op = states[rn].get("opponent") or {}
            oid = op.get("player_id")
            ob = board_ids_of(op)
            if oid and ob:
                opp_hist.setdefault(oid, {})[rn] = ob
        for rn in sorted(states):
            if rn < 4 or rn > 19:
                continue
            built = build_round(states, my_char, career, opp_hist, rec, rn)
            if not built:
                continue
            me_fx, opp_fx, pool_hand, target, visible, my_hist, human = built
            if not visible:
                continue
            kw = dict(my_boards_by_round=my_hist, my_hand=pool_hand, rnd=rn,
                      fast=fast, top_k=1)
            # LIVE: model prediction from what live actually sees
            rl = O.live_best_lines(me_fx, opp_fx, visible,
                                   use_board_model=True, **kw)
            # TRUE: exact target board given, no prediction
            rt = O.live_best_lines(me_fx, opp_fx, [target],
                                   use_board_model=False, opp_max_boards=1, **kw)
            if not (rl and rl.get("pick_board") and rt and rt.get("pick_board")):
                continue
            s_h = score(me_fx, opp_fx, human, target, rn)
            s_l = score(me_fx, opp_fx, rl["pick_board"], target, rn)
            s_t = score(me_fx, opp_fx, rt["pick_board"], target, rn)
            hsum += s_h; lsum += s_l; tsum += s_t
            h_win += (s_h > 0); l_win += (s_l > 0); t_win += (s_t > 0)
            l_resc += (s_l > 0 and s_h <= 0); l_break += (s_h > 0 and s_l <= 0)
            t_resc += (s_t > 0 and s_h <= 0); t_break += (s_h > 0 and s_t <= 0)
            net = rec[rn].get("net")
            if isinstance(net, int) and net != 0:
                agree += ((s_h > 0) == (net > 0))
            n += 1
            if n % 15 == 0:
                print(f"[{n}] HUMAN {100*h_win/n:.0f}%/{hsum/n:+.1f}  "
                      f"LIVE {100*l_win/n:.0f}%/{lsum/n:+.1f}  "
                      f"TRUE {100*t_win/n:.0f}%/{tsum/n:+.1f}", flush=True)

    m = max(n, 1)
    print(f"\n=== {n} rounds, TRUE fought boards as targets "
          f"(search={'fast' if fast else 'final'}) ===")
    print(f"{'arm':<30}{'win rate':>9}{'avg 命':>9}{'rescue/break':>14}")
    print(f"{'HUMAN (actual play)':<30}{100*h_win/m:>8.0f}%{hsum/m:>+9.2f}{'—':>14}")
    print(f"{'CALC LIVE (predicted)':<30}{100*l_win/m:>8.0f}%{lsum/m:>+9.2f}"
          f"{f'{l_resc}/{l_break}':>14}")
    print(f"{'CALC TRUE (exact board)':<30}{100*t_win/m:>8.0f}%{tsum/m:>+9.2f}"
          f"{f'{t_resc}/{t_break}':>14}")
    print(f"reconstruction validity: oracle-vs-record sign agreement "
          f"{100*agree/max(n,1):.0f}% (on decisive rounds)")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
