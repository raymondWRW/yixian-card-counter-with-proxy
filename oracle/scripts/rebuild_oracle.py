#!/usr/bin/env python3
"""
rebuild_oracle.py — the ONE command that (re)builds the Yi Xian Oracle to maximum parity from a fresh
game decompile. A game update becomes a single invocation; no hand-patching, no archaeology.

    python rebuild_oracle.py                      # facades -> build -> heal -> validate
    python rebuild_oracle.py --validate-only DIR  # just score parity against a battle corpus
    python rebuild_oracle.py --only facades       # run a single stage

────────────────────────────────────────────────────────────────────────────────────────────────────
THE WHOLE SYSTEM IN ONE SENTENCE:  "headless == the real game with INERT visuals."

The oracle runs the REAL decompiled combat code. The only things that don't work headless are VISUAL:
external engine types (no native binding) and serialized UI references (null — Unity never loaded the
prefab). So we make visuals inert and let the real gameplay run. Two mechanisms, both data-driven and
game-version-agnostic, are all that's needed — every past one-off fix is a special case of these:

  A. COMPLETE FACADES (FacadeGen, Stage 1).  Every external type becomes a runnable stub:
       • method bodies return NON-NULL inert values (the game dereferences facade results),
       • InternalCall / PInvoke / abstract methods are given real IL bodies (else a concrete type that
         declares one — e.g. UnityEngine.UI.Image.get_transform — fails to JIT-load),
       • explicit-interface-impl MethodImpl links that Il2CppDumper DROPPED are repaired,
       • any still-missing inherited interface/abstract slot is synthesized.
     Result: EVERY referenced type JIT-loads. (This killed the TypeLoad wall that blocked surviving the
     real UI init path — and auto-fixed a class of non-HD faults for free.)

  B. INSTRUCTION-LEVEL "SURVIVE" (AutoPatch.SurviveHeadless, applied by the doctor, Stage 3).  For a
     method that's mostly visual, restore its ORIGINAL body and neutralize ONLY the headless-breaking
     instructions — elide calls into visual engine types, and lazy-non-null any null reference field
     (the owning UI object is ctor-skipped, so its serialized refs are null) — keeping every gameplay
     DATA store. The bit-exact parity sweep accepts/rejects each transform, so it is safe by construction.

  C. STRUCTURAL GAMEPLAY-MIRROR FIXES (DllPatcher, applied unconditionally; all version-agnostic — they match
     by TYPE/METHOD NAME, not offsets, so a game update doesn't break them):
       • MOCK PASS — rebuild every UI setter as a pure backing-field store (render dropped), so UI-owned combat
         state (characterUI.tempLife += x, ...) lands. One rule, auto-detected across all UI setters.
       • cardConfig REDIRECT — KeYinItem.get_cardConfig reads the live model (battleKeYinCards[index]) via an
         injected __owner link, so the game's OWN swap/levelUp sigil code runs correctly (no bespoke rewrite).
     These replaced the old hand IL rewrites (set_tempLife, swapKeYin, levelUpKeYin) — now deleted.

Everything else (the exact combat math) is the unmodified game code. We never re-implement a card.

────────────────────────────────────────────────────────────────────────────────────────────────────
STAGES (each independently runnable with --only):
  1 facades   regenerate complete facades from Il2CppDumper's DummyDll       (Oracle --gen-facades)
  2 build     compile the Oracle                                            (dotnet build -c Release)
  3 heal      auto-doctor: per faulting method try [survive, nop], keep what improves bit-exact parity,
              persist accepted fixes as DATA in auto_patch.json              (oracle_doctor.py)
  4 validate  score the local battle records: NATIVE SWEEP pass/total        (Oracle --records-dir)

PER GAME UPDATE — the whole procedure:
  1. scripts/extract_assets.py        pull the update: DarkSun.HotUpdate.dll, configs/, DummyDll
  2. python rebuild_oracle.py         facades -> build -> heal -> validate (uses YIXIAN_RECORDS_DIR by default)
  3. scripts/snapshot_version.py      archive the working version under data/versions/<V>/
The structural fixes (A/B/C) carry over automatically. CROSS-VERSION CAVEAT: validating OLD records on a NEW
DLL shows <100% purely from balance patches (rebalanced card values) — that is NOT an oracle bug; validate with
CURRENT-version records (your freshly-recorded battles after the update).
"""
import argparse, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_ORACLE = os.path.abspath(os.path.join(HERE, ".."))
CSPROJ = os.path.join(GAME_ORACLE, "Oracle", "Oracle.csproj")
DLL_REL = os.path.join(GAME_ORACLE, "Oracle", "bin", "Release", "net8.0", "Oracle.dll")
DLL_DBG = os.path.join(GAME_ORACLE, "Oracle", "bin", "Debug", "net8.0", "Oracle.dll")
DOCTOR = os.path.join(HERE, "oracle_doctor.py")
# The user's local battle records — the always-present, CURRENT-version validation corpus. After a game update,
# these are the freshly-recorded current-version battles, so a pass here = the new version is reproduced correctly.
DEFAULT_RECORDS = os.environ.get(
    "YIXIAN_RECORDS_DIR",
    r"C:\Users\danhc\AppData\LocalLow\DarkSunStudio\YiXianPai\userLocalDatas\68e92665d06c85745f644008\recentBattleDatas")


def banner(stage, msg):
    print(f"\n{'='*92}\n[{stage}] {msg}\n{'='*92}", flush=True)


def run(cmd, **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, **kw)


def stage_facades():
    banner("1 FACADES", "regenerate COMPLETE facades from Il2CppDumper DummyDll")
    p = run(["dotnet", DLL_REL, "--gen-facades"], capture_output=True, text=True)
    tail = (p.stdout + p.stderr).strip().splitlines()[-1:] or ["(no output)"]
    print("   " + tail[-1])
    if p.returncode != 0:
        sys.exit("  [!] facade generation failed (build the Oracle first: --only build)")


def stage_build():
    banner("2 BUILD", "compile the Oracle (Release)")
    for cfg in ("Release", "Debug"):   # Release: runtime; Debug: oracle_doctor default
        p = run(["dotnet", "build", CSPROJ, "-c", cfg, "-v", "q", "--nologo"])
        if p.returncode != 0:
            sys.exit(f"  [!] {cfg} build failed")
    print("  build OK (Release + Debug)")


def stage_heal(records_dir, passes):
    records_dir = records_dir or (DEFAULT_RECORDS if os.path.isdir(DEFAULT_RECORDS) else None)
    banner("3 HEAL", f"auto-doctor over {records_dir} (survive/nop, keep what improves bit-exact parity)")
    if not records_dir:
        print("  [skip] no record set (set YIXIAN_RECORDS_DIR or pass --heal-records DIR); skipping heal.")
        return
    dll = DLL_DBG if os.path.exists(DLL_DBG) else DLL_REL
    p = run([sys.executable, DOCTOR, "--records-dir", records_dir, "--oracle-dll", dll, "--passes", str(passes)])
    if p.returncode != 0:
        print("  [warn] doctor returned nonzero (residuals reported above); continuing to validate.")


def stage_validate(corpus_dir, limit):
    corpus_dir = corpus_dir or (DEFAULT_RECORDS if os.path.isdir(DEFAULT_RECORDS) else None)
    banner("4 VALIDATE", f"score battle records {corpus_dir}")
    if not corpus_dir:
        print("  [skip] no validation corpus (set YIXIAN_RECORDS_DIR or pass --corpus DIR).")
        return
    t0 = time.time()
    # .bin records dir -> NATIVE SWEEP; exported <id>_pN.json corpus -> JSON RECORDS.
    import glob
    is_bin = glob.glob(os.path.join(corpus_dir, "**", "*.bin"), recursive=True) and not \
             glob.glob(os.path.join(corpus_dir, "**", "*_p*.json"), recursive=True)
    cmd = ["dotnet", DLL_REL, "--records-dir", corpus_dir] if is_bin else \
          ["dotnet", DLL_REL, "--run-json-records", corpus_dir, "--limit", str(limit)]
    p = run(cmd, capture_output=True, text=True)
    for line in p.stdout.splitlines():
        if re.search(r"=== (JSON RECORDS|NATIVE SWEEP)", line) or "% ===" in line:
            print("  " + line.strip())
    print(f"  NOTE: <100% is usually CROSS-VERSION (old records replayed on the new DLL after a balance patch), "
          f"NOT an oracle bug — confirm by checking that failures involve recently-rebalanced cards.")
    print(f"  ({time.time()-t0:.0f}s)")


def main():
    ap = argparse.ArgumentParser(description="One-command rebuild of the Yi Xian Oracle to max parity.")
    ap.add_argument("--only", choices=["facades", "build", "heal", "validate"], help="run a single stage")
    ap.add_argument("--validate-only", metavar="DIR", help="shortcut: run ONLY the parity validation on DIR")
    ap.add_argument("--corpus", metavar="DIR", help="shared-battle corpus dir for the validate stage")
    ap.add_argument("--heal-records", metavar="DIR", help=".bin record set for the heal (doctor) stage")
    ap.add_argument("--limit", type=int, default=60000, help="max battle files to validate")
    ap.add_argument("--passes", type=int, default=3, help="doctor candidate passes")
    args = ap.parse_args()

    if args.validate_only:
        stage_validate(args.validate_only, args.limit); return

    order = ["facades", "build", "heal", "validate"]
    stages = [args.only] if args.only else order
    for s in stages:
        if s == "facades":  stage_facades()
        elif s == "build":  stage_build()
        elif s == "heal":   stage_heal(args.heal_records, args.passes)
        elif s == "validate": stage_validate(args.corpus, args.limit)

    if not args.only:
        print("\n  done. The oracle is rebuilt; accepted fixes live in auto_patch.json (data, not code).")


if __name__ == "__main__":
    main()
