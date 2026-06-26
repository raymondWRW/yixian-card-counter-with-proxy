#!/usr/bin/env python3
"""
extract_mirror_model_map.py — derive the VISUAL-MIRROR -> GAMEPLAY-MODEL map from the game's own code.

The gap-#2 bug class: gameplay code reads a value off a VISUAL mirror (characterUI.hp, keYinItems[i].cardConfig,
m_CurrentUsingCard.cardConfig, ...). Headless the mirror is stale, so the read is wrong. But the game itself
keeps the mirror in sync with the canonical MODEL via assignments like `characterUI.hp = battleTempData.hp`.
Those assignments ARE the mirror->model mapping — we don't guess it, we extract it.

This scans the ilspy decompile for `<visualMirror>.<field> = <modelExpr>;` (and the reverse), groups by the
mirror field, and emits:
  (a) data/game/mirror_model_map.json  — {visualField: {model: "<expr>", sites: N}} the redirect mechanism uses,
  (b) a human report: every mirror field, its model source, and whether gameplay READS it (a redirect target).

This is the "capture all" surface: every model/mirror redundancy the game defines, derived automatically so it
regenerates on any patch.  Run:  uv run python tools/game-oracle/scripts/extract_mirror_model_map.py [decompile]
"""
from __future__ import annotations
import json, re, sys, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEC = Path(r"C:/Users/danhc/AppData/Local/Temp/hu/DarkSun.HotUpdate.decompiled.cs")
OUT = ROOT / "data" / "game" / "mirror_model_map.json"

# Visual mirror accessors (objects whose fields are inert/stale headless).
MIRROR = r"(?:characterUI|battleCharacterUI|m_CurrentUsingCard|m_CurrentUsingKeYinCard|keYinItem|keYinItems\[[^\]]+\])"
# Gameplay-bearing fields a mirror can hold (the things combat actually reads).
FIELD = r"(cardConfig|cardInfo|sourceCardConfig|tempLife|hp|maxHp|def|anima|exp)"
# A model source expression looks like battleTempData.* / playerData.* / publicData.* / lastRoundData.* / m_*.
MODEL = re.compile(r"\b(battleTempData|playerData|publicData|lastRoundData|m_[A-Z]\w*|battleKeYinCards)\b")

write_re = re.compile(rf"{MIRROR}\s*\.\s*{FIELD}\s*=\s*([^;]+);")
read_re  = re.compile(rf"{MIRROR}\s*\.\s*{FIELD}\b")


def main() -> None:
    dec = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DEC
    text = dec.read_text(encoding="utf-8", errors="ignore")
    lines = text.split("\n")

    # mirror field -> Counter of model RHS expressions (the sync writes define the mapping)
    field_model: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    field_reads: dict[str, int] = collections.Counter()
    read_examples: dict[str, str] = {}

    for ln in lines:
        for m in write_re.finditer(ln):
            field, rhs = m.group(1), m.group(2).strip()
            if MODEL.search(rhs):                       # RHS is a model expression -> it's a sync write
                # normalise rhs to its model tail (e.g. "battleTempData.hp")
                mm = re.search(rf"((?:battleTempData|playerData|publicData|lastRoundData|battleKeYinCards|m_[A-Z]\w*)\.[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)", rhs)
                field_model[field][mm.group(1) if mm else rhs[:40]] += 1
        for m in read_re.finditer(ln):
            field = m.group(1)
            # crude read vs write: a read is a use not immediately followed by '='
            after = ln[m.end():].lstrip()
            if after.startswith("=") and not after.startswith("=="):
                continue                                 # it's the LHS of a write, already counted above
            field_reads[field] += 1
            read_examples.setdefault(field, ln.strip()[:120])

    out = {}
    for field, models in field_model.items():
        model, n = models.most_common(1)[0]
        out[field] = {"model": model, "write_sites": sum(models.values()),
                      "read_sites": field_reads.get(field, 0),
                      "all_models": dict(models)}
    # UI-OWNED fields: read for gameplay but with NO `mirror.field = model.field` sync write (cardConfig, ...).
    # Still a gameplay-mirror that combat reads — emit it (model=None) so the surface join is COMPLETE; it just
    # can't be fixed by a flat redirect (needs persist/back-ref). Without this the hardest case (KeYin cardConfig)
    # would be silently absent from the map.
    for field, reads in field_reads.items():
        if field not in out:
            out[field] = {"model": None, "write_sites": 0, "read_sites": reads, "all_models": {}, "ui_owned": True}
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"=== mirror -> model map (derived from the game's own sync writes) -> {OUT} ===\n")
    print(f"{'mirror.field':<16}{'model source':<34}{'writes':>7}{'reads':>7}   verdict")
    for field in sorted(out, key=lambda f: -out[f]["read_sites"]):
        o = out[field]
        reads = o["read_sites"]
        # a redirect TARGET = gameplay reads the mirror AND we know the model source
        verdict = "REDIRECT TARGET" if reads > 0 and o["model"] else ("sync-only (no gameplay read)" if reads == 0 else "no model source")
        print(f"  {field:<14}{o['model']:<34}{o['write_sites']:>7}{reads:>7}   {verdict}")
    # fields read for gameplay but with NO sync write (UI-owned state, e.g. tempLife) -> persist, don't redirect
    only_read = sorted(set(field_reads) - set(field_model))
    if only_read:
        print("\n  UI-OWNED (read for gameplay, NO model sync write -> persist the field, can't redirect):")
        for f in only_read:
            print(f"    {f:<14} reads={field_reads[f]}   e.g. {read_examples.get(f,'')}")


if __name__ == "__main__":
    main()
