# -*- coding: utf-8 -*-
"""Distill the season9 replay-analysis build data into a compact heuristic table
the live calculator can bundle.

Source (dev-only, NOT shipped): the `yixian replay analysis` project's
site/data/season9_builds.json (~6MB) — per (character, career) it holds the top
board compositions per realm phase (`boards`) and the boards played against each
opponent character (`mboards`), as family indices (levels collapsed). `families`
maps each family index to a representative real card id (`img`).

Output: proxy/lines_heuristic.json — for each build, the top few card-id boards
per realm and per opponent character, with win rates. This seeds the live Nash
calc's candidate boards (especially the OPPONENT columns, where coverage of the
real counter boards is what makes the equilibrium trustworthy).

Usage:
  python tools/distill_lines_heuristic.py [path/to/season9_builds.json]
Default source path is the sibling `yixian replay analysis` project.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SRC = REPO.parent / "yixian replay analysis" / "site" / "data" / "season9_builds.json"
OUT = REPO / "proxy" / "lines_heuristic.json"

TOP_COMMON = 6     # board archetypes kept per (build, realm)
TOP_COUNTER = 4    # boards kept per (build, opponent character)
MIN_GAMES = 8      # drop boards with too few raw games (noise)


def distill(src: Path) -> dict:
    data = json.loads(src.read_text(encoding="utf-8"))
    builds = data["builds"]
    fams = data["families"]
    img = [f.get("img", 0) for f in fams]   # family index -> representative card id

    def to_cards(famidx):
        return [int(img[i]) for i in famidx if 0 <= i < len(img) and img[i]]

    def pack(board_entries, top_n):
        """board_entries: [[famidx, raw_games, w_count, w_wins, variations], ...]
        already frequency-sorted by the source. Keep top_n with enough games."""
        out = []
        for e in board_entries[:top_n * 2]:
            famidx, raw, wc, ww = e[0], e[1], e[2], e[3]
            if raw < MIN_GAMES or not wc:
                continue
            cards = to_cards(famidx)
            if not cards:
                continue
            out.append([cards, raw, round(ww / wc, 3)])     # [card ids, games, winrate]
            if len(out) >= top_n:
                break
        return out

    common, counter = {}, {}
    for key, b in builds.items():
        cm = {}
        for realm, entries in (b.get("boards") or {}).items():
            packed = pack(entries, TOP_COMMON)
            if packed:
                cm[str(realm)] = packed
        if cm:
            common[key] = cm
        ct = {}
        for opp_char, entries in (b.get("mboards") or {}).items():
            packed = pack(entries, TOP_COUNTER)
            if packed:
                ct[str(opp_char)] = packed
        if ct:
            counter[key] = ct
    return {
        "_source": src.name,
        "_note": "Per build '{charId}_{career}': common=top boards by realm phase; "
                 "counter=top boards played vs each opponent characterId. Card ids are "
                 "real Oracle ids (level = representative). Used to seed live Nash candidates.",
        "common": common,
        "counter": counter,
    }


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    if not src.exists():
        sys.exit(f"source not found: {src}\nPass the path to season9_builds.json as an argument.")
    print(f"reading {src} ({src.stat().st_size/1e6:.1f} MB) …", flush=True)
    table = distill(src)
    OUT.write_text(json.dumps(table, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    nb = len(table["common"])
    nc = sum(len(v) for v in table["counter"].values())
    print(f"wrote {OUT.relative_to(REPO)} ({OUT.stat().st_size/1e3:.0f} KB) — "
          f"{nb} builds, {nc} build-vs-opponent counter sets")


if __name__ == "__main__":
    main()
