#!/usr/bin/env python3
"""find_culprits.py — the auto-FINDER half of the find→fix loop.

Encodes the manual correlation that surfaced Li Man (character 4000005): run the oracle over the shared
JSON battle corpus, then rank the CARDS and CHARACTERS most responsible for failures by FAIL-RATE (not raw
count — controls for how common a card is). Crucially it CLASSIFIES each culprit:

  * FAULT-driven  -> a swallowed exception aborts the card/character's play (the Li Man class). These are
                    AUTO-FIXABLE: feed the fault method to oracle_doctor (now cascade-aware) -> nop/stub.
  * SILENT        -> clean execution, wrong value (a mis-modeled mechanic / RNG over-draw). NOT auto-fixable
                    by nop/stub; needs reading the card's mechanic + the code (the harder, human loop).

So a fresh game build's regressions get triaged automatically: "these N cards are FAULT culprits -> run the
doctor; these M are SILENT -> investigate these mechanics", pointing the next effort at the right layer.

Usage:
  python find_culprits.py <records_dir> [--limit N] [--oracle-dll <path>] [--min 40]
"""
import argparse, os, re, subprocess, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_ORACLE = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(GAME_ORACLE, "..", ".."))
DEFAULT_DLL = os.path.join(GAME_ORACLE, "Oracle", "bin", "Release", "net8.0", "Oracle.dll")
R_RE = re.compile(r"^R (?P<p>[01]) sm=(?P<sm>-?\d+) char=(?P<char>\d+) hperr=(?P<he>-?\d+) fault=(?P<fault>\S+) cards=(?P<cards>[\d,]*)")


def card_names():
    import json
    p = os.path.join(ROOT, "data", "game", "card_id_mapping.json")
    try:
        m = json.load(open(p, encoding="utf-8"))
        return {str(v["game_id"]): v.get("name_en", "?") for v in m.values() if v.get("game_id") is not None}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("records_dir")
    ap.add_argument("--limit", type=int, default=8000)
    ap.add_argument("--oracle-dll", default=DEFAULT_DLL)
    ap.add_argument("--min", type=int, default=40, help="min appearances for a card/char to be ranked")
    args = ap.parse_args()

    env = dict(os.environ); env["ORACLE_FAIL_CARDS"] = "1"
    cmd = ["dotnet", args.oracle_dll, "--run-json-records", os.path.abspath(args.records_dir), "--limit", str(args.limit)]
    print(f"running oracle over {args.records_dir} (limit {args.limit})...", file=sys.stderr)
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)

    # per-key: total appearances, fail appearances, fault-fail appearances
    card = collections.defaultdict(lambda: [0, 0, 0])   # [total, fail, faultfail]
    char = collections.defaultdict(lambda: [0, 0, 0])
    summary = None
    for line in p.stdout.splitlines():
        if line.startswith("=== JSON RECORDS"):
            summary = line
            continue
        m = R_RE.match(line)
        if not m:
            continue
        failed = m["p"] == "0"
        faulted = failed and m["fault"] != "none"
        c = char[m["char"]]; c[0] += 1; c[1] += failed; c[2] += faulted
        for cid in (m["cards"].split(",") if m["cards"] else []):
            if not cid:
                continue
            e = card[cid]; e[0] += 1; e[1] += failed; e[2] += faulted

    nm = card_names()
    print(summary or "(no summary)")

    def rank(d, label, name=lambda k: ""):
        rows = [(k, t, f, ff) for k, (t, f, ff) in d.items() if t >= args.min and f > 0]
        rows.sort(key=lambda r: r[2] / r[1], reverse=True)
        print(f"\n=== top {label} by fail-rate (>= {args.min} appearances) ===")
        print(f"  {'id':>9}  fails/total  rate  kind            name")
        for k, t, f, ff in rows[:20]:
            rate = 100 * f / t
            faultpct = 100 * ff / f if f else 0
            kind = "FAULT(doctor)" if faultpct >= 60 else ("SILENT(model)" if faultpct <= 20 else "MIXED")
            print(f"  {k:>9}  {f:>4}/{t:<5} {rate:4.0f}%  {kind:<14}  {name(k)}")

    rank(char, "CHARACTERS", lambda k: "")
    rank(card, "CARDS", lambda k: nm.get(k, "?"))


if __name__ == "__main__":
    main()
