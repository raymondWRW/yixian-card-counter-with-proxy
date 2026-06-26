#!/usr/bin/env python3
"""
build_season_slice.py — build a small CURATED battle slice that EXERCISES every season mechanic, for fast
season-safe validation (e.g. by prune_hand_fixes.py). A hand-fix is only safe to delete if skipping it holds
parity on battles covering every season/card path it touches; a single-season slice over-reports obsolescence
(per the cron-cycle-4 finding). This samples N battles per seasonMec into one dir so a prune/validation run is
both FAST (few files) and GENERALIZING (all seasons present).

    python build_season_slice.py --corpus <BIG_corpus_dir> --out <slice_dir> [--per 14] [--seasons 0,7,8,9]

seasonMec: 0=None 1=QiYun 2=XXMF 3=FateBranch 4=ImmortalRelic 5=TalentResonance 6=Mirage 7=KeYin 8=Dream
9=FateStrategy(HD). Default samples the 4 that dominate the corpus (0,7,8,9).
"""
import argparse, glob, json, os, shutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, help="big shared-battle corpus dir (recursively scanned)")
    ap.add_argument("--out", required=True, help="output slice dir (recreated)")
    ap.add_argument("--per", type=int, default=14, help="battles per season")
    ap.add_argument("--seasons", default="0,7,8,9", help="comma seasonMec values to cover")
    args = ap.parse_args()

    want = {int(s): args.per for s in args.seasons.split(",") if s.strip()}
    have = {k: 0 for k in want}
    shutil.rmtree(args.out, ignore_errors=True)
    os.makedirs(args.out, exist_ok=True)
    seen, n = set(), 0
    for f in glob.glob(os.path.join(args.corpus, "**", "*_p0.json"), recursive=True):
        if all(have[k] >= want[k] for k in want):
            break
        try:
            d = json.load(open(f, encoding="utf-8"))["data"]
            sm, gid = d.get("seasonMec"), d.get("gameId")
        except Exception:
            continue
        if sm not in want or have[sm] >= want[sm] or gid in seen:
            continue
        seen.add(gid); have[sm] += 1; n += 1
        shutil.copy(f, os.path.join(args.out, os.path.basename(f)))
    print(f"copied {n} battles to {args.out}: {have}")
    missing = [k for k in want if have[k] < want[k]]
    if missing:
        print(f"  [warn] under-filled seasons (not enough battles in corpus): {missing}")


if __name__ == "__main__":
    main()
