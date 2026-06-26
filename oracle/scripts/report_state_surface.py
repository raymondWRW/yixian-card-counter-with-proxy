#!/usr/bin/env python3
"""
report_state_surface.py — the JOIN that turns the raw static surface into the actionable closed set.

Two artifacts already exist:
  - data/game/oracle_audit/state_index.json   (Oracle --gen-state-index): every gameplay-typed read off a visual
    VIEW mirror, across every card/sigil/fate effect. The complete candidate surface — but it can't tell a
    gameplay primitive (characterUI.hp) from a cosmetic one (animator.skinColor) by type alone.
  - data/game/mirror_model_map.json           (extract_mirror_model_map.py): the mirror.field -> model source map
    DERIVED from the game's own `mirror.field = model.field` sync writes — the authoritative list of which view
    fields actually mirror gameplay state, and each one's verdict (redirect-target / sync-only / UI-owned-hard).

Joining them: a static-surface read is a REAL GAMEPLAY MIRROR iff its field name appears in the model map.
Everything else is cosmetic (animator/hp-bar/floating-text) and drops out. The result is the closed, classified
gameplay-mirror surface the headless runner must get right — derived end-to-end, no hand list.

    uv run python tools/game-oracle/scripts/report_state_surface.py
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INDEX = ROOT / "data" / "game" / "oracle_audit" / "state_index.json"
MAP = ROOT / "data" / "game" / "mirror_model_map.json"


def fieldname(member: str) -> str:
    """`BattleCharacterUI.get_tempLife` / `KeYinItem.<cardConfig>k__BackingField` / `..m_TempLife` -> `tempLife`."""
    m = member.split(":")[0].split(".")[-1]
    m = m.replace("k__BackingField", "").strip("<>")
    if m.startswith(("get_", "set_")):
        m = m[4:]
    if m.startswith("m_"):
        m = m[2:]
    return m


def main() -> None:
    if not INDEX.exists():
        raise SystemExit(f"missing {INDEX} — run: dotnet Oracle.dll --gen-state-index")
    if not MAP.exists():
        raise SystemExit(f"missing {MAP} — run: extract_mirror_model_map.py")
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    mmap = json.loads(MAP.read_text(encoding="utf-8"))
    # case-insensitive lookup of model-map fields
    mkeys = {k.lower(): k for k in mmap}

    surface = idx["surface"]
    gameplay: dict[str, dict] = {}   # field -> {members, total_reads, model, verdict}
    cosmetic = 0
    for member, info in surface.items():
        fld = fieldname(member)
        mk = mkeys.get(fld.lower())
        if mk is None:
            cosmetic += 1
            continue
        e = gameplay.setdefault(mk, {"members": set(), "reads": 0,
                                     "model": mmap[mk].get("model", "?"),
                                     "model_writes": mmap[mk].get("write_sites", 0),
                                     "model_reads": mmap[mk].get("read_sites", 0)})
        e["members"].add(member.split(":")[0])
        e["reads"] += info["count"]

    def verdict(fld: str) -> str:
        o = mmap[fld]
        if o.get("read_sites", 0) == 0:
            return "SYNC-ONLY (combat reads the model — no bug)"
        if o.get("model"):
            return f"REDIRECT-TARGET (model: {o['model']})"
        return "UI-OWNED (no model sync — hard; needs persist/back-ref)"

    # OBJECT mirrors: a read whose member TYPE is a gameplay CONFIG / CardInfo off a mirror view (cardConfig,
    # cardInfo). The numeric model-map join can't see these (no flat int sync), but combat branches on them, so
    # they're real gameplay mirrors. Cosmetic *Data types (CompareData/KeywordDetailData) are NOT Config/CardInfo.
    obj: dict[str, dict] = {}
    for member, info in surface.items():
        mtype = member.split(":")[-1]
        if mtype.endswith("Config") or mtype == "CardInfo":
            e = obj.setdefault(member.split(":")[0], {"type": mtype, "reads": 0})
            e["reads"] += info["count"]

    print(f"=== gameplay-mirror surface (state_index x mirror_model_map) ===")
    print(f"  static candidates: {len(surface)} distinct reads across {idx['entry_points_with_mirror_reads']} effects")
    print(f"  cosmetic (no model sync — animator/hp-bar/floating-text, dropped): {cosmetic}")
    print(f"  NUMERIC GAMEPLAY MIRRORS (model-map backed): {len(gameplay)}\n")
    print(f"  {'field':<12}{'effects':>8}{'reads':>7}   verdict")
    for fld in sorted(gameplay, key=lambda f: -gameplay[f]["reads"]):
        g = gameplay[fld]
        print(f"  {fld:<12}{len(g['members']):>8}{g['reads']:>7}   {verdict(fld)}")
    print(f"\n  OBJECT GAMEPLAY MIRRORS (config/info read off a view — branch-on-able state): {len(obj)}")
    for mem in sorted(obj, key=lambda m: -obj[m]["reads"]):
        print(f"    {obj[mem]['reads']:>5}x  {mem}:{obj[mem]['type']}")
    # any model-map gameplay field NOT seen in the static surface = a read the static pass missed (or unused)
    seen = {f.lower() for f in gameplay}
    missed = [k for k in mmap if k.lower() not in seen and mmap[k].get("read_sites", 0) > 0]
    if missed:
        print(f"\n  NOTE: model-map gameplay fields not surfaced statically (investigate transitive/virtual reads): {missed}")


if __name__ == "__main__":
    main()
