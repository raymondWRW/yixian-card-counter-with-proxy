# -*- coding: utf-8 -*-
"""gen_card_types.py — regenerate proxy/card_types.json from the game card db.

A board may legally hold at most 2 [消耗] (consumption) cards and at most 2 [持续]
(continuous) cards — separate caps, verified on 463k replay boards (99.7% comply;
the exceptions correlate with career perks: >2 消耗 only 炼丹师/符箓师, >2 持续
mostly 阵法师). The calculator filters candidate builds with these flags
(oracle_sim._my_candidates et al.), defaulting to the strict cap and raising it
only when a live board已经 legally exceeds it.

Flags come from the game's own desc markers: the bracketed type tokens [消耗] /
[持续] in desc_cn (bracket-matching avoids false positives like "灵气消耗减1").
Stored at LINE level (level stripped) — levels share the type.

Run after a game patch refreshes tools/cards_game.json:
    python tools/gen_card_types.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "cards_game.json")
OUT = os.path.join(HERE, "..", "proxy", "card_types.json")


def line_of(c):
    return c - ((c // 10000) % 100) * 10000


def main():
    db = json.load(open(SRC, encoding="utf-8"))
    cons, cont, names = set(), set(), {}
    for e in db["entries"]:
        d = e.get("desc_cn") or ""
        ln = line_of(e["id"])
        names.setdefault(ln, e.get("name_cn") or "")
        if "[消耗]" in d:
            cons.add(ln)
        if "[持续]" in d:
            cont.add(ln)
    out = {
        "consumption": sorted(cons),
        "continuous": sorted(cont),
        "_names": {str(l): names.get(l, "") for l in sorted(cons | cont)},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"wrote {OUT}: {len(cons)} consumption, {len(cont)} continuous "
          f"({len(cons & cont)} both)")


if __name__ == "__main__":
    main()
