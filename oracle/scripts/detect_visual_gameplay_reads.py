#!/usr/bin/env python3
"""
detect_visual_gameplay_reads.py — STATIC detector for the "gameplay reads from an INERT visual" bug class.

The headless oracle nops/stubs all VISUAL objects, so their fields are null/unsynced. When real game-code reads
a GAMEPLAY value (cardConfig/cardInfo/an id/a stat) off one of those visual objects and uses it for gameplay,
headless it silently gets null/0 (null-safe `?? 0`, never crashes) -> wrong gameplay -> a parity residual the
crash/parity auto-fixer CANNOT see (no NRE, no single attributable method). This is exactly how the KeYin
swapKeYin (read keYinItems[i].cardConfig) and levelUpKeYin bugs slipped through.

This scans the ilspy decompile for that pattern: a GAMEPLAY field/property read off a VISUAL accessor, where
the value then feeds a gameplay write/return. Output = ranked candidate methods to inspect (and bespoke-fix to
read the gameplay source, e.g. battleTempData.battleKeYinCards, instead of the visual mirror).

    python detect_visual_gameplay_reads.py <decompiled.cs>
"""
import re, sys, collections

# VISUAL accessors/roots whose fields are inert headless (these mirror gameplay state on the UI).
VISUAL_ROOTS = [
    r"characterUI", r"battleCharacterUI", r"\.keYinItems\[[^\]]+\]", r"\.battleCardItems\[[^\]]+\]",
    r"\.defItem", r"\.animaItem", r"\.keYinItem\b", r"\.tipoItem", r"\.lifeItem",
    r"m_CurrentUsingKeYinCard", r"m_CurrentUsingCard", r"\.animator\b", r"keYinItem\b",
]
# GAMEPLAY values that, when read OFF a visual object, are the bug (config/id/stat the UI merely displays).
GAMEPLAY_FIELDS = r"(cardConfig|cardInfo|tempLife|\bhp\b|\bdef\b|\banima\b|\bmaxHp\b|sourceCardConfig)"
# gameplay sinks that prove the visual read feeds real gameplay (heuristic, used to rank).
GAMEPLAY_SINK = re.compile(r"battleKeYinCards|battleTempData|ModifyBuffValue|ModifyHp|ModifyDef|ModifyAnima|SetBuffValue|= levelUp|RemoveBuff")

read_re = re.compile(r"(" + "|".join(VISUAL_ROOTS) + r")\s*\.\s*" + GAMEPLAY_FIELDS)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/danhc/AppData/Local/Temp/hu/DarkSun.HotUpdate.decompiled.cs"
    lines = open(path, encoding="utf-8", errors="ignore").read().split("\n")
    # find enclosing method name for each line (last 'Type Method(...)' / 'public ... (' before it)
    methsig = re.compile(r"^\s*(?:public|private|internal|protected|static|\s)+[\w<>,\.\[\]]+\s+([A-Za-z_]\w*)\s*\(")
    cur = "?"
    hits = collections.defaultdict(list)  # method -> [(line, text, has_sink)]
    method_at = [None]*len(lines)
    for i, ln in enumerate(lines):
        m = methsig.match(ln)
        if m and "=" not in ln.split("(")[0]:
            cur = m.group(1)
        method_at[i] = cur
    for i, ln in enumerate(lines):
        for mm in read_re.finditer(ln):
            # skip pure-visual reads (transform/position) and writes (assignment target)
            field = mm.group(2)
            # is it a READ (value used) vs a WRITE (lhs)? crude: if '=' appears AFTER the match and not '=='/'!=', and match is left of '=', it's a write -> still interesting but mark.
            window = "\n".join(lines[max(0,i-2):i+4])
            has_sink = bool(GAMEPLAY_SINK.search(window))
            hits[method_at[i]].append((i+1, ln.strip()[:130], has_sink, field))
    # rank: methods with a gameplay sink near a visual-config read first
    ranked = sorted(hits.items(), key=lambda kv: (-sum(1 for h in kv[1] if h[2]), -len(kv[1])))
    print(f"=== {sum(len(v) for v in hits.values())} visual-gameplay reads across {len(hits)} methods ===\n")
    print("--- HIGH PRIORITY: visual gameplay-config read FEEDS a gameplay sink (the swapKeYin/levelUpKeYin class) ---")
    for meth, hh in ranked:
        sinks = [h for h in hh if h[2]]
        if not sinks: continue
        print(f"\n  {meth}  ({len(sinks)} sink-adjacent):")
        for ln, txt, sink, fld in sinks[:4]:
            print(f"    L{ln} [{fld}] {txt}")
    print("\n--- (lower priority: visual reads without an obvious adjacent gameplay sink omitted; rerun without filter to see) ---")

if __name__ == "__main__":
    main()
