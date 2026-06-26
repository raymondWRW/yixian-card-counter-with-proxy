#!/usr/bin/env python3
"""
detect_mirror_dependencies.py — AUTOMATIC, mapping-free detector for the gap-#2 "gameplay reads a stale
visual mirror" class. Run it each patch; it surfaces every mirror dependency in the game and flags which are
currently HANDLED (baseline parity holds) vs NEWLY UNHANDLED (a handler is missing/broken).

How: visuals are supposed to be inert. So we run the shared-battle corpus three ways and diff per-round:
  1. NORMAL                                   (baseline, hand-fixes on)
  2. ORACLE_PERTURB_MIRRORS=1                 (EVERY int getter on EVERY ILRComponentBase UI type, offset +0x4000)
  3. ORACLE_PERTURB_MIRRORS_OBJ=1 (+int)      (cardConfig getters return a wrong-but-VALID empty CardConfig, id=0)
A round whose result MOVES under a perturbation READ that mirror for gameplay -> a dependency. No mirror->model
map needed. For each dependency we also report baseline pass/fail: PASS = handled, FAIL = needs a handler.

The object perturbation returns a wrong-but-VALID object (NOT null): null NREs the render path and floods the
diff with crash-aborts (1510 on the HD corpus) instead of real reads. A non-null wrong object is the exact
object-analogue of the int +0x4000 offset — rendering survives, only a real field-read off it moves a round.
Caveat: object mirrors that are correctly populated headless (KeYinCardItem.cardConfig, the general card item)
will MOVE-but-be-HANDLED; the genuinely-stale one is the keYinItems[i] sigil grid, exercised only on a KeYin
corpus. INT mirrors are clean (0 moved on HD = combat reads the model, never an int mirror).

CORPUS: pass either a local .bin records dir (always present, driven via --records-dir + --results-out) or an
exported <id>_pN.json corpus (driven via --run-json-records R-lines). Auto-detected.

    uv run python tools/game-oracle/scripts/detect_mirror_dependencies.py <corpus_dir> [--limit N]
"""
from __future__ import annotations
import re, subprocess, sys, collections, argparse, json, os, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DLL = ROOT / "tools" / "game-oracle" / "Oracle" / "bin" / "Release" / "net8.0" / "Oracle.dll"
RLINE = re.compile(r"^R (\d+) .*hperr=(-?\d+).* rnd=(\d+) src=(\S+).* cards=(\S*)")
RESKEY = re.compile(r"^(?P<src>.+)-r(?P<rnd>\d+)$")


def _is_bin_corpus(corpus: str) -> bool:
    """A local .bin records dir (always present) vs an exported <id>_pN.json corpus."""
    return any(Path(corpus).rglob("*.bin")) and not any(Path(corpus).rglob("*_p*.json"))


def run(corpus: str, limit: int, env_extra: dict[str, str]) -> dict[tuple, tuple]:
    env = {**os.environ, **env_extra, "ORACLE_FAIL_CARDS": "1"}
    out: dict[tuple, tuple] = {}
    if _is_bin_corpus(corpus):
        # records-dir sweep: per-round data is written to --results-out (pass/simHpDelta/recHpDelta).
        # This is the always-present local .bin corpus path — no separate JSON export needed.
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            res_path = tf.name
        try:
            subprocess.run(["dotnet", str(DLL), "--records-dir", corpus, "--results-out", res_path],
                           capture_output=True, text=True, env=env, cwd=str(DLL.parent))
            data = json.loads(Path(res_path).read_text(encoding="utf-8"))
        finally:
            try: os.unlink(res_path)
            except OSError: pass
        for key, v in data.items():
            m = RESKEY.match(key)
            if not m:
                continue
            hperr = int(v.get("simHpDelta", 0)) - int(v.get("recHpDelta", 0))
            out[(m.group("src"), int(m.group("rnd")))] = (1 if v.get("pass") else 0, hperr, "")
        return out
    # exported JSON-records corpus: parse R-lines (carries cards involved).
    p = subprocess.run(["dotnet", str(DLL), "--run-json-records", corpus, "--limit", str(limit)],
                       capture_output=True, text=True, env=env, cwd=str(DLL.parent))
    for ln in p.stdout.splitlines():
        m = RLINE.match(ln.strip())
        if m:
            rpass, hperr, rnd, src, cards = m.groups()
            out[(src, int(rnd))] = (int(rpass), int(hperr), cards)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("--limit", type=int, default=4000)
    a = ap.parse_args()
    if not DLL.exists():
        raise SystemExit(f"build the oracle first: {DLL} missing")

    print("running NORMAL ...");           base = run(a.corpus, a.limit, {})
    print("running INT-perturbed ...");    pint = run(a.corpus, a.limit, {"ORACLE_PERTURB_MIRRORS": "1"})
    print("running OBJ-perturbed ...");    pobj = run(a.corpus, a.limit, {"ORACLE_PERTURB_MIRRORS": "1", "ORACLE_PERTURB_MIRRORS_OBJ": "1"})

    # a round depends on a mirror if its (pass,hperr) moved under a perturbation
    def moved(k, other):
        b = base.get(k); o = other.get(k)
        return b and o and (b[0] != o[0] or b[1] != o[1])
    int_dep = [k for k in base if moved(k, pint)]
    obj_dep = [k for k in base if moved(k, pobj) and k not in set(int_dep)]

    def report(name, deps):
        handled = [k for k in deps if base[k][0] == 1]   # baseline passes -> a handler covers it
        unhandled = [k for k in deps if base[k][0] == 0]  # baseline fails  -> needs a handler
        print(f"\n=== {name} mirror dependencies: {len(deps)} rounds  (handled {len(handled)} / UNHANDLED {len(unhandled)}) ===")
        cards = collections.Counter()
        for k in deps:
            for c in base[k][2].split(","):
                if c and c != "0":
                    cards[c] += 1
        print("  cards most-involved:", dict(cards.most_common(8)))
        if unhandled:
            print("  !! UNHANDLED (baseline fails — a stale-mirror handler is missing/broken):")
            for k in unhandled[:10]:
                print(f"     {k[0]} rnd {k[1]}  cards={base[k][2]}")

    print(f"\nbaseline rounds: {len(base)} | exact: {sum(1 for v in base.values() if v[0]==1)}")
    report("INT (hp/def/anima/maxHp/exp/tempLife)", int_dep)
    report("OBJECT (cardConfig: keYin)", obj_dep)
    print("\n(Every dependency listed reads a visual mirror for gameplay. HANDLED = a seed/redirect/bespoke "
          "already covers it; UNHANDLED = newly-surfaced, needs one.)")


if __name__ == "__main__":
    main()
