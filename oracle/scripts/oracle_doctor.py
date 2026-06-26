#!/usr/bin/env python3
"""
oracle_doctor.py — the closed auto-patch loop for the native Oracle.

Ties together the pieces built in AutoPatch.cs into a self-driving loop:

    sweep (current spec) -> gather candidates -> try a patch -> re-sweep ->
    KEEP iff pass-rate rose with no pass->fail regression, else REVERT -> repeat to fixpoint.

The patches are DATA (a JSON spec read at runtime by DllPatcher via ORACLE_AUTO_PATCH), so the loop NEVER
rebuilds — it just edits the spec and re-runs the sweep. The bit-exact sweep is the oracle that accepts or
rejects each heuristic patch, which is what makes automatic patching safe. Anything the templates can't fix
is left alone and reported (escalated), never silently masked.

Candidate sources (both gameplay-loss, the class this loop targets — NOT pure DMG/setup accuracy):
  1. DETECTOR  — methods whose original body wrote gameplay but whose patched body lost it
                 (`ORACLE_DETECT_NOPS=1`). Found without needing a crash.
  2. FAULTS    — the method named in each round's `fault` field.
For each candidate, try actions in order [survive, stub, nop]; keep the first that helps.

Usage:
  python oracle_doctor.py --records-dir <dir> [--oracle-dll <path>] [--spec <out.json>] [--passes 3]

Honest scope: this drives the FAULT/dropped-gameplay class toward 0. The remaining DMG-DIFF/TURN misses
(battle runs, wrong number) are a separate problem; the loop reports them but does not try to invent values.
"""
import argparse, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_ORACLE = os.path.abspath(os.path.join(HERE, ".."))
DEFAULT_DLL = os.path.join(GAME_ORACLE, "Oracle", "bin", "Debug", "net8.0", "Oracle.dll")
DEFAULT_SPEC = os.path.join(GAME_ORACLE, "auto_patch.json")

DETECT_RE = re.compile(r"\[detect-nop\] overbroad nop \(gameplay dropped\): (?P<type>[^.]+)\.(?P<method>[^(]+)\((?P<sig>[^)]*)\)")
FAULT_RE = re.compile(r"@ (?P<type>[^.]+)\.(?P<method>[^+]+)\+IL_")


# Known grouped/single dict mappings for configs that live ONLY in a ConfigManager dict (no list field):
#   config -> "Name@dictField/keyField[*]"  (* = grouped Dictionary<key,List<Config>>)
# Grows as we learn them; configs not here are tried list-only (TryPlaceConfigList in the runner).
KNOWN_CONFIG_DICTS = {
    "CharacterAnimClipConfig": "CharacterAnimClipConfig@charAnimClipDict/charId*",
}


def run(dll, args, spec_path, out_path=None, detect=False, load_configs=None):
    """Run Oracle.dll with the given spec + extra config loads applied; return (stdout, results_or_None)."""
    env = dict(os.environ)
    if spec_path and os.path.exists(spec_path):
        env["ORACLE_AUTO_PATCH"] = spec_path
    if load_configs:
        env["ORACLE_LOAD_CONFIGS"] = ",".join(load_configs)
    if detect:
        env["ORACLE_DETECT_NOPS"] = "1"
    cmd = ["dotnet", dll] + args
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1800)
    out = p.stdout + "\n" + p.stderr
    results = None
    if out_path and os.path.exists(out_path):
        try:
            results = json.load(open(out_path, encoding="utf-8"))
        except Exception:
            results = None
    return out, results


def sweep(dll, records_dir, spec_path, work_dir, tag, load_configs=None):
    out_path = os.path.join(work_dir, f"results_{tag}.json")
    if os.path.exists(out_path):
        os.remove(out_path)
    out, results = run(dll, ["--records-dir", records_dir, "--results-out", out_path], spec_path, out_path,
                       load_configs=load_configs)
    # A process-killing record (uncatchable stack overflow) leaves NO results file — treat as catastrophic.
    return results, out


def score(results):
    if not results:
        return (-1, -1)  # catastrophic (process died / no file)
    npass = sum(1 for v in results.values() if v.get("pass"))
    nfault = sum(1 for v in results.values() if v.get("fault"))
    return (npass, -nfault)


def regressions(base, trial):
    if not base or not trial:
        return 999
    return sum(1 for k, v in base.items() if v.get("pass") and not (trial.get(k, {}) or {}).get("pass"))


def _fault_method(v):
    f = (v or {}).get("fault")
    if not f:
        return None
    m = FAULT_RE.search(f)
    return (m["type"].strip(), m["method"].strip()) if m else None


def fault_shifted(base, trial, spec_methods):
    """CASCADE detection: a still-failing round whose fault moved to a method NOT yet in the spec = progress.
    Lets the loop chain nops through a multi-method fault cascade (e.g. CardItem ResetDescription ->
    SetKeywordGray -> SetNameLabel) that the strict pass-rate/fault-count criterion alone can't cross —
    each individual nop looks worthless until the whole chain is nopped. Dead links are pruned afterward."""
    if not base or not trial:
        return False
    for k, bv in base.items():
        tv = trial.get(k, {}) or {}
        if tv.get("pass") or not tv.get("fault"):
            continue
        tm = _fault_method(tv)
        if tm and tm != _fault_method(bv) and tm not in spec_methods:
            return True
    return False


def detector_candidates(dll, spec_path):
    out, _ = run(dll, [], spec_path, detect=True)  # default probe; detector prints during DLL load
    cands = []
    for m in DETECT_RE.finditer(out):
        cands.append((m["type"], m["method"].strip(), m["sig"].strip()))
    return cands


def fault_candidates(results):
    seen, cands = set(), []
    for v in (results or {}).values():
        f = v.get("fault")
        if not f:
            continue
        m = FAULT_RE.search(f)
        if not m:
            continue
        t, meth = m["type"].strip(), m["method"].strip()
        if t.startswith("<"):   # compiler-gen state machine (<Foo>d__N) — not a directly-patchable method
            continue
        key = (t, meth)
        if key in seen:
            continue
        seen.add(key)
        cands.append((t, meth, ""))   # sig unknown from a fault; FindMethod picks the overload
    return cands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records-dir", required=True)
    ap.add_argument("--oracle-dll", default=DEFAULT_DLL)
    ap.add_argument("--spec", default=DEFAULT_SPEC, help="accepted-patch spec to grow (persisted)")
    ap.add_argument("--passes", type=int, default=3, help="max full candidate passes")
    ap.add_argument("--actions", default="survive,stub,nop", help="action ladder per candidate")
    ap.add_argument("--try-configs", default="",
                    help="comma list of UNLOADED config names to trial-load (from `ildump configaudit`); "
                         "kept if the load improves pass-rate. Dict-only tables use KNOWN_CONFIG_DICTS.")
    args = ap.parse_args()

    dll = os.path.abspath(args.oracle_dll)
    if not os.path.exists(dll):
        sys.exit(f"Oracle.dll not found: {dll}\n  build: dotnet build tools/game-oracle/Oracle/Oracle.csproj -c Debug")
    records_dir = os.path.abspath(args.records_dir)
    spec_path = os.path.abspath(args.spec)
    work_dir = tempfile.mkdtemp(prefix="oracle_doctor_")

    # Load (or start) the accepted spec.
    spec = []
    if os.path.exists(spec_path):
        try: spec = json.load(open(spec_path, encoding="utf-8"))
        except Exception: spec = []
    def write_spec(s): json.dump(s, open(spec_path, "w", encoding="utf-8"), indent=2)
    def in_spec(t, m, sig): return any(e["type"] == t and e["method"] == m and (e.get("sig") or "") == sig for e in spec)
    write_spec(spec)

    print(f"=== oracle_doctor ===\n  dll: {dll}\n  records: {records_dir}\n  spec: {spec_path} ({len(spec)} patches)\n  work: {work_dir}\n")

    accepted_configs = []   # extra config-load specs that improved (passed to ORACLE_LOAD_CONFIGS)

    best, best_out = sweep(dll, records_dir, spec_path, work_dir, "best", load_configs=accepted_configs)
    if best is None:
        print("  [!] baseline sweep produced NO results (a record crashed the process). The loop needs a\n"
              "      completing baseline — fix/exclude the process-killing record first.")
        # still try: candidates from the partial stdout faults are unavailable; bail.
        sys.exit(1)
    bp, bf = score(best)
    print(f"  baseline: {bp}/{len(best)} exact, {-bf} faulting rounds\n")

    # ── CONFIG PHASE: trial-load each unloaded combat config (cause: combat reads a null/empty table) ──
    cfg_cands = [c.strip() for c in args.try_configs.split(",") if c.strip()]
    if cfg_cands:
        print(f"  config phase: {len(cfg_cands)} candidate(s)")
        for name in cfg_cands:
            spec_str = KNOWN_CONFIG_DICTS.get(name, name)   # dict mapping if known, else list-only by name
            trial, _ = sweep(dll, records_dir, spec_path, work_dir, "trial", load_configs=accepted_configs + [spec_str])
            tp, tf = score(trial); reg = regressions(best, trial)
            if reg == 0 and ((tp > bp) or (tp == bp and tf > bf)):
                accepted_configs.append(spec_str); best, bp, bf = trial, tp, tf
                print(f"    + KEEP  load {name:<40} -> {bp}/{len(best)} exact, {-bf} faults")
            else:
                why = "process died" if trial is None else f"{tp}/{-tf}f reg={reg}"
                print(f"    - skip  load {name:<40} ({why})")
        print()

    actions = [a.strip() for a in args.actions.split(",") if a.strip()]
    tried = set()
    for pass_i in range(1, args.passes + 1):
        # Re-gather candidates each pass (accepted patches drop off the detector; new faults may appear).
        cands = detector_candidates(dll, spec_path) + fault_candidates(best)
        fresh = [c for c in cands if c not in tried and not in_spec(*c)]
        if not fresh:
            print(f"  pass {pass_i}: no fresh candidates — fixpoint reached.")
            break
        print(f"  pass {pass_i}: {len(fresh)} candidate(s)")
        accepted_this_pass = 0
        for (t, m, sig) in fresh:
            tried.add((t, m, sig))
            label = f"{t}.{m}({sig})"
            for action in actions:
                entry = {"type": t, "method": m, "sig": sig, "action": action}
                spec.append(entry); write_spec(spec)
                trial, _ = sweep(dll, records_dir, spec_path, work_dir, "trial", load_configs=accepted_configs)
                tp, tf = score(trial)
                reg = regressions(best, trial)
                improved = reg == 0 and ((tp > bp) or (tp == bp and tf > bf))
                spec_methods = {(e["type"], e["method"]) for e in spec}
                shifted = reg == 0 and not improved and fault_shifted(best, trial, spec_methods)
                if improved or shifted:
                    best, bp, bf = trial, tp, tf
                    tag = "KEEP " if improved else "CHAIN"   # CHAIN = speculative cascade link (pruned later if dead)
                    print(f"    + {tag} {label:<55} [{action}]  -> {bp}/{len(best)} exact, {-bf} faults")
                    accepted_this_pass += 1
                    break
                else:
                    spec.pop(); write_spec(spec)   # revert
                    why = "process died" if trial is None else f"{tp}/{-tf}f reg={reg}"
                    print(f"    - skip  {label:<55} [{action}]  ({why})")
        if accepted_this_pass == 0:
            print(f"  pass {pass_i}: nothing accepted — fixpoint reached.")
            break

    # PRUNE: remove any patch that isn't load-bearing (speculative CHAIN links whose cascade didn't pan out,
    # or anything made redundant later). Remove it, re-sweep; if pass-rate holds and no regression, drop it.
    print("  prune pass:")
    i = 0
    while i < len(spec):
        saved = spec.pop(i); write_spec(spec)
        trial, _ = sweep(dll, records_dir, spec_path, work_dir, "prune", load_configs=accepted_configs)
        tp, tf = score(trial)
        if trial is not None and tp >= bp and regressions(best, trial) == 0:
            print(f"    - drop  {saved['type']}.{saved['method']} [{saved['action']}] (not load-bearing)")
            best, bp, bf = trial, tp, tf   # state without it
        else:
            spec.insert(i, saved); write_spec(spec); i += 1   # keep it

    print(f"\n=== done: {bp}/{len(best)} exact, {-bf} faulting rounds; {len(spec)} patches in {spec_path} ===")
    # Report the residual (the class this loop does NOT fix) so it's escalated, not hidden.
    resid_fault = sorted({(FAULT_RE.search(v['fault']).group(0) if v.get('fault') and FAULT_RE.search(v['fault']) else v.get('fault'))
                          for k, v in best.items() if not v.get("pass") and v.get("fault")})
    resid_dmg = sum(1 for v in best.values() if not v.get("pass") and not v.get("fault"))
    if resid_fault:
        print("  residual FAULTs the templates could not fix (escalate):")
        for f in resid_fault[:20]:
            print(f"    ! {f}")
    print(f"  residual non-crash DMG/TURN misses (separate accuracy work, not this loop): {resid_dmg}")


if __name__ == "__main__":
    main()
