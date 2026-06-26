#!/usr/bin/env python3
"""
oracle_triage.py — turn the Oracle sweep's opaque pass-rate into an ACTIONABLE, prioritized fix list.

The native runner writes per-round results to data/fixtures/_results.json (via --records-dir
--results-out, see fast_sweep.sh). Each round carries: pass, simHpDelta/recHpDelta, simTurns/recTurns,
and `fault` (the first un-nopped game method that threw, or null for a clean run).

This tool classifies every non-passing round, then CLUSTERS the clean divergences so a single underlying
mechanic shows up as one cluster instead of N scattered failures. It's the "investigation" half of the
near-autonomous loop: it tells you WHAT is wrong and WHERE to look, ranked by leverage (rounds fixed per
fix). The "fixing" half is then either:
  - FAULT clusters  -> nop the named visual method in DllPatcher.PatchForNative (mechanical, often
                       auto-applicable), then re-sweep.
  - DMG/TURN clusters-> open the named record+rounds with ORACLE_TRACE_ROUND=<n> to read the exact
                       diverging hit, identify the mechanic (buff/physique/passive/card), fix it.

Usage:
  python oracle_triage.py                     # full triage report over _results.json
  python oracle_triage.py --record bst4q5e    # deep-dive one record (every round + delta)
  python oracle_triage.py --results <path>    # use a different results json
  python oracle_triage.py --top 25            # show more clusters
"""
import argparse, collections, json, os, re, sys

DEFAULT_RESULTS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "fixtures", "_results.json")

ROUND_RE = re.compile(r"^(?P<rec>.+)-r(?P<rnd>\d+)$")


def classify(v):
    """Return (category, detail) for one round result dict."""
    if v.get("pass"):
        return ("PASS", None)
    if v.get("fault"):
        # fault string: "<ExceptionType> @ <Type>.<Method>+IL_xxxx: msg" — key by Type.Method+ExcType.
        f = v["fault"]
        head = f.split(":", 1)[0]                      # "<ExcType> @ <Type>.<Method>+IL_xxxx"
        exc = head.split(" @ ", 1)[0].strip()
        site = head.split(" @ ", 1)[1].strip() if " @ " in head else "?"
        site = site.split("+IL_")[0]                   # drop the volatile IL offset
        return ("FAULT", f"{exc} @ {site}")
    sh, rh = v.get("simHpDelta"), v.get("recHpDelta")
    st, rt = v.get("simTurns"), v.get("recTurns")
    if sh is None or rh is None or st is None or rt is None:
        return ("NODATA", None)
    if st >= 64:
        return ("HANG", "turns hit the 64 cap (self-retriggering action-again chain)")
    if (sh > 0) != (rh > 0) and sh != 0 and rh != 0:
        return ("WINNER-FLIP", f"sim {sh} vs rec {rh}")
    if st < rt - 1:
        return ("TURN-SHORT", f"sim ends {rt-st} turns early (extra damage / missing heal-revive)")
    if st > rt + 1:
        return ("TURN-LONG", f"sim runs {st-rt} turns long (missing termination / under-damage)")
    if st == rt:
        return ("DMG-DIFF", f"Δ={sh-rh:+d} (turns exact)")
    return ("OTHER", f"sim {sh}/{st}t vs rec {rh}/{rt}t")


def rec_of(key):
    m = ROUND_RE.match(key)
    return m.group("rec") if m else key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=DEFAULT_RESULTS)
    ap.add_argument("--record", default=None, help="deep-dive a single record stem")
    ap.add_argument("--baseline", default=None,
                    help="diff current results against a baseline json: show regressions + fixes")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    path = os.path.abspath(args.results)
    if not os.path.exists(path):
        sys.exit(f"results not found: {path}\n(run tools/game-oracle/scripts/fast_sweep.sh first)")
    data = json.load(open(path, encoding="utf-8"))

    # ── verify: diff against a baseline (did the last fix help or regress?) ──────
    if args.baseline:
        base = json.load(open(os.path.abspath(args.baseline), encoding="utf-8"))
        regressed, fixed = [], []
        for k, v in data.items():
            bv = base.get(k)
            if bv is None:
                continue
            was, now = bool(bv.get("pass")), bool(v.get("pass"))
            if was and not now:
                regressed.append(k)
            elif now and not was:
                fixed.append(k)
        bp = sum(1 for v in base.values() if v.get("pass"))
        np_ = sum(1 for v in data.values() if v.get("pass"))
        print(f"=== DIFF vs baseline ===")
        print(f"  baseline: {bp}/{len(base)} exact   current: {np_}/{len(data)} exact   "
              f"net {np_-bp:+d} rounds")
        print(f"  FIXED (fail->pass): {len(fixed)}")
        for k in sorted(fixed)[:args.top]:
            print(f"    + {k}")
        print(f"  REGRESSED (pass->fail): {len(regressed)}   <-- investigate these FIRST")
        for k in sorted(regressed):
            cat, det = classify(data[k])
            print(f"    - {k}   now {cat} {det or ''}")
        return

    # ── single-record deep dive ────────────────────────────────────────────────
    if args.record:
        rows = sorted((k, v) for k, v in data.items() if rec_of(k) == args.record)
        if not rows:
            sys.exit(f"no rounds for record '{args.record}'")
        print(f"=== {args.record}: {len(rows)} rounds ===")
        for k, v in rows:
            cat, det = classify(v)
            rnd = ROUND_RE.match(k).group("rnd")
            flag = "ok " if cat == "PASS" else "MISS"
            print(f"  r{rnd:>2} {flag} {cat:<12} sim {v.get('simHpDelta')}/{v.get('simTurns')}t  "
                  f"rec {v.get('recHpDelta')}/{v.get('recTurns')}t   {det or ''}")
        print("\n  -> trace a diverging round:  ORACLE_TRACE_ROUND=<n> dotnet run ... (then read the hp/buff sequence)")
        return

    # ── full triage ────────────────────────────────────────────────────────────
    total = len(data)
    cat_counts = collections.Counter()
    by_record = collections.defaultdict(lambda: collections.Counter())   # record -> category -> n
    dmg_by_record_delta = collections.defaultdict(list)                   # (record, delta) -> [round keys]
    fault_clusters = collections.defaultdict(list)                       # fault sig -> [round keys]

    for k, v in data.items():
        cat, det = classify(v)
        cat_counts[cat] += 1
        if cat == "PASS":
            continue
        by_record[rec_of(k)][cat] += 1
        if cat == "FAULT":
            fault_clusters[det].append(k)
        elif cat == "DMG-DIFF":
            dmg_by_record_delta[(rec_of(k), v["simHpDelta"] - v["recHpDelta"])].append(k)

    npass = cat_counts["PASS"]
    print(f"=== ORACLE TRIAGE: {npass}/{total} rounds exact ({100*npass/total:.1f}%) ===\n")
    print("failure shape breakdown:")
    for c, n in cat_counts.most_common():
        if c == "PASS":
            continue
        print(f"  {n:5} ({100*n/(total-npass):4.1f}% of misses)  {c}")

    # FAULT clusters first — these are mechanical (nop / facade), highest ROI when present.
    if fault_clusters:
        print(f"\n--- FAULT clusters (nop the method in PatchForNative, or add the facade member) ---")
        for sig, rounds in sorted(fault_clusters.items(), key=lambda kv: -len(kv[1]))[:args.top]:
            print(f"  [{len(rounds):3} rounds] {sig}")
            print(f"            e.g. {rounds[:4]}")

    # Systematic DMG-DIFF clusters: same record + same delta across multiple rounds == ONE mechanic.
    sys_clusters = {k: r for k, r in dmg_by_record_delta.items() if len(r) >= 2}
    print(f"\n--- systematic DMG-DIFF clusters (same record off by the SAME amount = one mechanic) ---")
    print(f"    {len(sys_clusters)} clusters cover {sum(len(r) for r in sys_clusters.values())} rounds; "
          f"top {args.top} by leverage:")
    for (rec, delta), rounds in sorted(sys_clusters.items(), key=lambda kv: -len(kv[1]))[:args.top]:
        print(f"  [{len(rounds):3} rounds] {rec}  every miss off by Δ={delta:+d}  -> one buff/physique/passive/card")
        print(f"            rounds {sorted(int(ROUND_RE.match(k).group('rnd')) for k in rounds)}")

    # Records where the WHOLE record fails one way — strongest single-fix leverage.
    print(f"\n--- records most worth fixing (most non-pass rounds, dominant shape) ---")
    ranked = sorted(by_record.items(), key=lambda kv: -sum(kv[1].values()))[:args.top]
    for rec, cats in ranked:
        miss = sum(cats.values())
        dom = cats.most_common(1)[0]
        print(f"  [{miss:3} miss] {rec:<14} dominant: {dom[0]} ({dom[1]})   all: {dict(cats)}")

    print(f"\nnext: `python oracle_triage.py --record <stem>` to see a record's rounds, "
          f"then ORACLE_TRACE_ROUND=<n> to read the diverging hit.")


if __name__ == "__main__":
    main()
