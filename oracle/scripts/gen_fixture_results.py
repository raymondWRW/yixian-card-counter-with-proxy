#!/usr/bin/env python
"""Generate data/fixtures/_results.json — per-fixture (per-round) combat results for the Oracle test
list, so the UI can pre-load PASS/MISS without a ~3000-run "Run All".

Runs Oracle `--batch --execute --record <bin>` once per record (fast: one process validates every
round) and parses the per-round lines into { "{stem}-r{NN}": {...} }. Combat-only criterion
(hpDelta+turns); destiny is flagged separately (server-side survive fates), never a miss.

Usage:  uv run python tools/game-oracle/scripts/gen_fixture_results.py
"""
from __future__ import annotations
import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ORACLE = ROOT / "tools" / "game-oracle" / "Oracle"
REC = Path(os.environ.get(
    "YIXIAN_RECORDS_DIR",
    r"C:\Users\danhc\AppData\LocalLow\DarkSunStudio\YiXianPai\userLocalDatas\68e92665d06c85745f644008\recentBattleDatas",
))
OUT = ROOT / "data" / "fixtures" / "_results.json"

# "  round 14: ✓ EXACT  hpΔ   -44/-44    turns  13/13   life  -22/-5  ⚑destiny(server-side)"
LINE = re.compile(
    r"round\s+(\d+):.*?(EXACT|DIFF).*?hp\S*\s+(-?\d+)/(-?\d+)\s+turns\s+(-?\d+)/(-?\d+)\s+life\s+(-?\d+)/(-?\d+)"
)


def run_record(bin_path: Path) -> dict:
    env = {**os.environ, "ORACLE_MAXDEPTH": "1000"}
    try:
        p = subprocess.run(
            ["dotnet", "run", "--project", str(ORACLE / "Oracle.csproj"), "-c", "Release",
             "--no-build", "--", "--batch", "--execute", "--record", str(bin_path)],
            capture_output=True, text=True, timeout=90, cwd=str(ORACLE), env=env,
        )
        out = p.stdout
    except subprocess.TimeoutExpired:
        out = ""
    finally:
        subprocess.run(["taskkill", "/F", "/IM", "Oracle.exe"], capture_output=True)
    stem = bin_path.stem
    res = {}
    for m in LINE.finditer(out):
        rnd = int(m.group(1))
        res[f"{stem}-r{rnd:02d}"] = {
            "pass": m.group(2) == "EXACT",
            "destinyFlagged": "destiny" in out.split(m.group(0), 1)[-1][:60],
            "simHpDelta": int(m.group(3)), "recHpDelta": int(m.group(4)),
            "simTurns": int(m.group(5)), "recTurns": int(m.group(6)),
            "simLife": int(m.group(7)), "recLife": int(m.group(8)),
        }
    return res


def main():
    bins = sorted(REC.glob("*.bin"))
    if not bins:
        print(f"no records under {REC}", file=sys.stderr); sys.exit(1)
    results: dict = {}
    for i, b in enumerate(bins, 1):
        results.update(run_record(b))
        print(f"[{i}/{len(bins)}] {b.stem}: {sum(1 for k in results if k.startswith(b.stem))} rounds", file=sys.stderr)
    OUT.write_text(json.dumps(results, indent=0), encoding="utf-8")
    npass = sum(1 for v in results.values() if v["pass"])
    print(f"wrote {OUT} — {npass}/{len(results)} rounds combat-exact")


if __name__ == "__main__":
    main()
