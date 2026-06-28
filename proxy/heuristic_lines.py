# -*- coding: utf-8 -*-
"""heuristic_lines.py — read the distilled season build heuristics (lines_heuristic.json)
and serve candidate boards for the live Nash calc.

The data (built by tools/distill_lines_heuristic.py from replay analysis) holds, per
build "{characterId}_{career}":
  common[realm]    = top board archetypes that build plays at that realm phase.
  counter[oppChar] = top boards that build plays AGAINST a given opponent character.
Each board is [card_ids, raw_games, winrate].

We use these to SEED the live calc's candidate boards (especially the opponent
columns vs MY character — coverage of the real counters is what makes the
equilibrium trustworthy). The opponent's career isn't on the wire, so opponent
lookups aggregate across all careers for that character.

Pure prior: callers still score every board through the Oracle, so a stale table
(new season / game patch) only slows convergence, never makes the answer wrong.
"""
import json
import math
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "lines_heuristic.json"
_data = None


def _load() -> dict:
    global _data
    if _data is None:
        try:
            _data = json.loads(_PATH.read_text(encoding="utf-8"))
        except Exception:
            _data = {"common": {}, "counter": {}}
    return _data


def available() -> bool:
    d = _load()
    return bool(d.get("common") or d.get("counter"))


def _keys_for_char(sub: str, char) -> list:
    pre = f"{char}_"
    return [k for k in _load().get(sub, {}) if k.startswith(pre)]


def _rank(entries, top: int) -> list:
    """entries: list of [card_ids, games, winrate]. Dedup by card tuple, score by
    winrate weighted by log(games) (so a 70%-over-200-games board outranks a
    80%-over-9-games fluke), return the top `top` card-id lists."""
    best = {}
    for cards, games, wr in entries:
        t = tuple(cards)
        score = float(wr) * math.log1p(float(games))
        if t not in best or score > best[t][0]:
            best[t] = (score, list(cards))
    return [cards for _s, cards in sorted(best.values(), key=lambda x: -x[0])[:top]]


def common_boards(char, career=None, realm=None, top: int = 6) -> list:
    """Top board archetypes for `char`. career/realm optional — aggregate across
    all careers / realms when not given (with a fallback to all realms if the
    requested realm has no data)."""
    d = _load().get("common", {})
    keys = [f"{char}_{career}"] if career else _keys_for_char("common", char)
    out = []
    for k in keys:
        realms = d.get(k, {})
        rs = [str(realm)] if realm is not None and str(realm) in realms else list(realms.keys())
        for rr in rs:
            out.extend(realms.get(rr, []))
    return _rank(out, top)


def counter_boards(char, career, vs_char, top: int = 6) -> list:
    """Top boards that `char` (career optional → aggregate) plays AGAINST
    `vs_char`. For seeding the opponent's columns, call as
    counter_boards(opp_char, None, my_char)."""
    d = _load().get("counter", {})
    keys = [f"{char}_{career}"] if career else _keys_for_char("counter", char)
    out = []
    for k in keys:
        out.extend(d.get(k, {}).get(str(vs_char), []))
    return _rank(out, top)
