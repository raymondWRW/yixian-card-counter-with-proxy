#!/usr/bin/env python3
"""
prune_hand_fixes.py — safely SHRINK the hand-written visual-fix layer toward zero, using the parity corpus as
the oracle. With COMPLETE facades, many hand nops/stubs are now OBSOLETE (the method runs fine un-nopped). This
driver finds them: it leaves each hand-fixed TYPE un-nopped (ORACLE_HAND_SKIP="Type.*") with the rest of the
hand layer + bespoke patches ON, and measures parity. Type still 100% -> its hand fixes are OBSOLETE (delete
them). Parity drops -> still NEEDED (keep / re-derive). This is the SAFE incremental migration (vs the unsafe
from-zero rebuild): the 100% baseline instantly rejects any removal that drops gameplay.

    python prune_hand_fixes.py --corpus <dir> [--limit 150]

Outputs OBSOLETE vs NEEDED types. Deleting the OBSOLETE ones from DllPatcher's NopType/StubVisualType lists is
a pure, validated reduction of hand-written fixes.
"""
import argparse, glob, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_ORACLE = os.path.abspath(os.path.join(HERE, ".."))
DLL = os.path.join(GAME_ORACLE, "Oracle", "bin", "Release", "net8.0", "Oracle.dll")
SUMMARY = re.compile(r"=== (?:JSON RECORDS|NATIVE SWEEP): (\d+)/(\d+)")


def _is_bin_corpus(corpus):
    """A local .bin records dir (always present) vs an exported <id>_pN.json corpus."""
    return (glob.glob(os.path.join(corpus, "**", "*.bin"), recursive=True)
            and not glob.glob(os.path.join(corpus, "**", "*_p*.json"), recursive=True))


def _cmd(corpus, limit):
    # bin corpus -> records-dir sweep (NATIVE SWEEP summary); json corpus -> run-json-records (JSON RECORDS).
    if _is_bin_corpus(corpus):
        return ["dotnet", DLL, "--records-dir", corpus]
    return ["dotnet", DLL, "--run-json-records", corpus, "--limit", str(limit)]


def parity(corpus, limit, skip=None):
    env = dict(os.environ)
    if skip:
        env["ORACLE_HAND_SKIP"] = skip
    try:
        p = subprocess.run(_cmd(corpus, limit), env=env, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return -2, -2   # HUNG (skipping this method infinite-loops combat -> the fix is NEEDED)
    for line in p.stdout.splitlines():
        m = SUMMARY.search(line)
        if m:
            return int(m[1]), int(m[2])
    return -1, -1       # crashed / no summary -> NEEDED


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--limit", type=int, default=150)
    ap.add_argument("--methods", action="store_true",
                    help="drill PER-METHOD instead of per-type (finds obsolete individual methods inside a "
                         "type-level NEEDED type). Slower (one run per method).")
    args = ap.parse_args()
    corpus = os.path.abspath(args.corpus)

    # 1) export the hand visual-fix list to discover the types it touches
    exp = os.path.join(tempfile.gettempdir(), "handfix_list.json")
    env = dict(os.environ); env["ORACLE_EXPORT_HANDFIXES"] = exp
    # any run triggers the export during DLL patching (corpus-type-appropriate command)
    subprocess.run(_cmd(corpus, 1), env=env, capture_output=True, text=True, timeout=600)
    entries = json.load(open(exp))
    types = sorted({e["type"] for e in entries})
    print(f"hand visual-fix layer touches {len(entries)} methods across {len(types)} types\n")

    base_p, base_t = parity(corpus, args.limit)
    print(f"baseline (all hand fixes on): {base_p}/{base_t}  "
          f"({'100%' if base_p == base_t else 'has genuine residuals — OBSOLETE = matches THIS baseline'})\n")
    if base_p < 0:
        sys.exit("  [!] baseline crashed — fix that first.")
    # NOTE: OBSOLETE means a skip yields EXACTLY the all-fixes baseline (p==base_p and tot==base_t), so this
    # works on multi-season slices that aren't 100% (genuine residuals don't matter — we compare to baseline,
    # not to total). Prefer a slice that EXERCISES every season/card path the fixes touch, else candidates
    # won't generalize (per cron-cycle-4 finding).

    # build the unit list: per-type "Type.*" (default) or per-method "Type.Method" (--methods)
    units = [f"{t}.*" for t in types] if not args.methods else [f'{e["type"]}.{e["method"]}' for e in entries]
    obsolete, needed = [], []
    for i, u in enumerate(units, 1):
        p, tot = parity(corpus, args.limit, skip=u)
        tag = ("OBSOLETE" if (p == base_p and tot == base_t)
               else "HANG" if p == -2 else "CRASH" if p == -1 else "NEEDED")
        print(f"  [{i:>3}/{len(units)}] {u:<48} skip -> {p}/{tot}  [{tag}]", flush=True)
        (obsolete if tag == "OBSOLETE" else needed).append((u, 1))

    print(f"\n=== OBSOLETE types (hand fixes deletable — {sum(n for _,n in obsolete)} methods) ===")
    for t, n in obsolete: print(f"  {t} ({n})")
    print(f"\n=== STILL NEEDED types ({sum(n for _,n in needed)} methods) ===")
    for t, n in needed: print(f"  {t} ({n})")
    print(f"\nDeleting the OBSOLETE types from DllPatcher NopType/StubVisualType is a validated reduction.")
    print("Validate on the FULL corpus before removing, then re-run to confirm 100% holds.")


if __name__ == "__main__":
    main()
