#!/usr/bin/env python3
"""
sweep_versioned.py — version-ROUTED replay verification.

The correctness rule: a replay recorded under game version V must be verified against V's engine
(DLL + configs), never a newer build, or a later patch silently diverges old replays. This driver
enforces that. For each version snapshot in data/versions/, it runs the native Oracle PINNED to that
snapshot (`--store`) and FILTERED to only that version's replays (`--only-version`), then merges the
per-version results. Replays whose version has NO snapshot are reported as UNCOVERED — never run
against a mismatched version, never counted as failures.

This replaces a flat sweep (which ran every replay against whatever happened to be in data/extracted)
for any verification that must stay honest across game updates.

Usage:
  uv run python tools/game-oracle/scripts/sweep_versioned.py [--records-dir <dir>] [--out <results.json>]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
ORACLE_CSPROJ = os.path.join(ROOT, "tools", "game-oracle", "Oracle", "Oracle.csproj")
VERSIONS_DIR = os.path.join(ROOT, "data", "versions")
DEFAULT_RECORDS = (r"C:\Users\danhc\AppData\LocalLow\DarkSunStudio\YiXianPai\userLocalDatas"
                   r"\68e92665d06c85745f644008\recentBattleDatas")
DEFAULT_OUT = os.path.join(ROOT, "data", "fixtures", "_results.json")
BIN_VERSION_RE = re.compile(rb"00[0-9]\.[0-9]{4}\.[0-9]{4}[a-z]?")
SWEEP_LINE_RE = re.compile(r"NATIVE SWEEP: (\d+)/(\d+) rounds exact")


def replay_versions(records_dir: str) -> dict[str, int]:
    """version -> replay count across the corpus (read straight from each .bin)."""
    counts: dict[str, int] = {}
    for f in glob.glob(os.path.join(records_dir, "*.bin")):
        try:
            m = BIN_VERSION_RE.search(open(f, "rb").read())
        except OSError:
            continue
        v = m.group().decode() if m else "?unknown"
        counts[v] = counts.get(v, 0) + 1
    return counts


def covered_versions() -> set[str]:
    if not os.path.isdir(VERSIONS_DIR):
        return set()
    return {
        d for d in os.listdir(VERSIONS_DIR)
        if os.path.isfile(os.path.join(VERSIONS_DIR, d, "DarkSun.HotUpdate.dll"))
    }


def run_pinned(version: str, records_dir: str, out_path: str) -> tuple[int, int, str]:
    """Run the Oracle pinned to `version`'s snapshot, filtered to that version. Returns (pass, total, tail)."""
    store = os.path.join(VERSIONS_DIR, version)
    env = dict(os.environ)
    env["ORACLE_MAXDEPTH"] = env.get("ORACLE_MAXDEPTH", "1000")
    cmd = [
        "dotnet", "run", "--project", ORACLE_CSPROJ, "-c", "Release", "--no-build", "--",
        "--store", store, "--only-version", version,
        "--records-dir", records_dir, "--results-out", out_path,
    ]
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1800)
    out = p.stdout + "\n" + p.stderr
    m = SWEEP_LINE_RE.search(out)
    tail = next((ln for ln in out.splitlines() if "NATIVE SWEEP:" in ln), "(no sweep line)")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0), tail  # type: ignore


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records-dir", default=DEFAULT_RECORDS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    records_dir = os.path.abspath(args.records_dir)
    if not os.path.isdir(records_dir):
        sys.exit(f"records dir not found: {records_dir}")

    present = replay_versions(records_dir)
    covered = covered_versions()
    print(f"=== version-routed sweep: {sum(present.values())} replays, "
          f"{len(present)} versions present, {len(covered)} snapshots available ===\n")

    work_dir = tempfile.mkdtemp(prefix="sweep_versioned_")
    merged: dict[str, dict] = {}
    if os.path.exists(args.out):
        try:
            merged = json.load(open(args.out, encoding="utf-8"))
        except Exception:
            merged = {}

    total_pass = total_run = 0
    for version in sorted(present):
        n = present[version]
        if version not in covered:
            print(f"  {version:<16} {n:>4} replays  — UNCOVERED (no snapshot; skipped, not failed)")
            continue
        out_path = os.path.join(work_dir, f"routed_{version}.json")
        (p, t), tail = run_pinned(version, records_dir, out_path)
        pct = (100 * p / t) if t else 0.0
        print(f"  {version:<16} {n:>4} replays  -> {p}/{t} rounds exact ({pct:.1f}%)")
        total_pass += p
        total_run += t
        if os.path.exists(out_path):
            try:
                merged.update(json.load(open(out_path, encoding="utf-8")))
            except Exception as e:
                print(f"    ! merge skip {out_path}: {e}", file=sys.stderr)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(merged, open(args.out, "w", encoding="utf-8"), indent=0)

    uncovered = {v: present[v] for v in present if v not in covered}
    print(f"\n=== routed total: {total_pass}/{total_run} rounds exact "
          f"({100*total_pass/max(total_run,1):.1f}%) across covered versions; "
          f"{sum(uncovered.values())} replays in {len(uncovered)} uncovered versions skipped ===")
    if uncovered:
        print(f"    uncovered (need a snapshot to verify): {', '.join(sorted(uncovered))}")
    print(f"    merged -> {os.path.relpath(args.out, ROOT)}")


if __name__ == "__main__":
    main()
