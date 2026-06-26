#!/usr/bin/env python3
"""
auto_heal.py — the generic, hands-off engine that rebuilds the oracle's fix set as DATA, so we never
hand-write a headless conversion again. Runs with the hand-fix surface OFF (ORACLE_HAND_FIXES=0) on top of
COMPLETE facades, and discovers everything algorithmically from two signals: process crashes and parity.

    python auto_heal.py --corpus <battle_dir> [--limit N] [--out auto_patch.generated.json]

TWO PHASES (both write DATA to a spec file; nothing hand-authored):

  PHASE 1 — CRASH BOOTSTRAP.  Some visual methods throw on a background thread (async fire-and-forget, e.g.
    BattleExecuter.OnEnd) and kill the process before any per-round catch — so the doctor can't even get a
    baseline. We make the process COMPLETE by reading the crash STACK: take the first game frame, add it to
    the spec as `nop`, re-run, repeat until the corpus run completes. Purely mechanical, update-agnostic.

  PHASE 2 — PARITY HEAL.  With a completing baseline, drive off the per-round pass/fault lines that
    --run-json-records emits (ORACLE_FAIL_CARDS=1). For each faulting method try [survive, nop] and KEEP the
    first that raises exact-parity with NO pass->fail regression (the bit-exact corpus is the oracle that
    accepts/rejects each patch). Iterate to fixpoint, then prune non-load-bearing patches.

Output is a spec the runner loads via ORACLE_AUTO_PATCH. It is written to a SEPARATE file by default so the
live auto_patch.json / 100% default path is never disturbed until a human swaps it in after validation.
"""
import argparse, json, os, re, subprocess, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_ORACLE = os.path.abspath(os.path.join(HERE, ".."))
DEFAULT_DLL = os.path.join(GAME_ORACLE, "Oracle", "bin", "Release", "net8.0", "Oracle.dll")

# A stack frame:  "   at BattleExecuter.OnEnd(Action callback)"  /  "   at <Execute>d__52.MoveNext()"
FRAME_RE = re.compile(r"^\s+at\s+(?P<type>[A-Za-z0-9_.`+<>]+)\.(?P<method>[A-Za-z0-9_`<>]+)\(")
# An R-line (ORACLE_FAIL_CARDS=1):  "R {0|1} sm=.. char=.. hperr=.. fault=X @ Type.Method+IL.. game=G rnd=N .."
RLINE_RE = re.compile(r"^R (?P<p>[01]) .*? fault=(?P<fault>\S+(?: @ \S+)?) game=(?P<game>\S+) rnd=(?P<rnd>\d+)")
FAULT_AT_RE = re.compile(r"@ (?P<type>\S+?)\.(?P<method>\w+)\+IL_(?P<off>[0-9A-Fa-f]+)")
SUMMARY_RE = re.compile(r"=== JSON RECORDS: (?P<p>\d+)/(?P<t>\d+)")
ILDUMP_CALL_RE = re.compile(r"IL_(?P<off>[0-9A-Fa-f]+):\s+(?:call|callvirt|newobj)\s+(?P<type>[\w<>]+)\.(?P<method>[\w<>]+)")
SKIP_NS = ("System.", "Cysharp.", "Microsoft.", "Internal.", "Mono.")

DLL = None              # set in main(); used by resolve_fault
_resolve_cache = {}

# Combat-core methods the cascade heuristic must not mishandle. Two tiers:
#  NEVER_PATCH — pure getters / the driver: nop/stub/survive are all wrong (a getter just returns a field; the
#    cure for its null is fixing the UPSTREAM builder, not the getter). e.g. nopping get_battleParamsQueue ->
#    <Execute>d__52.MoveNext does null.Clear() -> NRE. The hand layer never touches these.
#  SURVIVE_ONLY — gameplay-state BUILDERS that throw only because a VISUAL sub-call inside them NRE'd: the cure
#    is SURVIVE (run the real body, elide just the visual sub-calls) so the gameplay work — building the RNG
#    queue / temp data — still happens. nop/stub here is catastrophic (nopped CreateTempData -> no RNG queue ->
#    the get_battleParamsQueue NRE above). The cascade-acceptance heuristic otherwise mistakes that MOVED crash
#    for "progress", so restrict these to survive-only.
NEVER_PATCH = {
    ("BattleExecuter", "get_battleParamsQueue"),
    ("BattleExecuter", "Execute"),
}
SURVIVE_ONLY = {
    ("BattleExecuter", "CreateTempData"),
}


_ildump_cache = {}


def _calls_in(typ, method):
    """All (offset, type, method) call sites in a method body (cached), via --ildump."""
    key = (typ, method)
    if key in _ildump_cache:
        return _ildump_cache[key]
    calls = []
    try:
        out = subprocess.run(["dotnet", DLL, "--ildump", typ, method], capture_output=True, text=True, timeout=120).stdout
        for line in out.splitlines():
            cm = ILDUMP_CALL_RE.search(line)
            if cm:
                calls.append((int(cm["off"], 16), cm["type"], cm["method"]))
    except Exception:
        pass
    _ildump_cache[key] = calls
    return calls


def resolve_fault(fault):
    """Return an ORDERED list of candidate (type, method) leaf calls to try for a fault '@ Type.Method+IL_off'.
    A NullReferenceException at a callvirt is usually a NULL RECEIVER produced by a call JUST BEFORE the offset
    (e.g. battlePanel = FindILRPanel() -> null -> SetBlockActive NRE) — stubbing that producer non-null fixes
    it. For async combat the captured frame is the state-machine MoveNext, not the visual method. So: collect
    the nearest preceding call sites (null sources, closest first) + the call AT/after the offset, and (for a
    real method frame) the frame itself. The heal tries them in order until parity/faults improve."""
    m = FAULT_AT_RE.search(fault or "")
    if not m:
        return []
    typ, meth, off = m["type"], m["method"], int(m["off"], 16)
    out = []
    if not typ.startswith("<"):
        out.append((typ.split("+")[-1], meth))          # the frame method itself (leaf in the sync case)
    calls = _calls_in(typ, meth if not typ.startswith("<") else "MoveNext")
    before = sorted([c for c in calls if c[0] <= off], key=lambda c: -c[0])[:4]   # nearest preceding first
    after = sorted([c for c in calls if c[0] > off], key=lambda c: c[0])[:1]
    for _, t, mm in before + after:
        if (t, mm) not in out:
            out.append((t, mm))
    return out


def _fault_id(v):
    """A stable identity for a round's fault (type+offset) — used to detect cascade SHIFT."""
    return (v or {}).get("fault")


def run_sweep(dll, corpus, limit, spec_path):
    env = dict(os.environ)
    # Heal the VISUAL nop/stub layer only (ORACLE_HAND_NOPS=0): bespoke reconstruction (Patch*Module + seeds)
    # stays ON, so combat is correct once visuals are made inert — parity is a real signal as we heal.
    env["ORACLE_HAND_NOPS"] = "0"
    env["ORACLE_FAIL_CARDS"] = "1"
    env["ORACLE_AUTO_PATCH"] = spec_path
    cmd = ["dotnet", dll, "--run-json-records", corpus, "--limit", str(limit)]
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
    return p.stdout + "\n" + p.stderr


def parse(out):
    """Return (results dict {key:{pass,fault}}, completed bool, npass, ntotal, crash_method_or_None)."""
    results, npass, ntotal, completed, crash = {}, 0, 0, False, None
    for line in out.splitlines():
        ms = SUMMARY_RE.search(line)
        if ms:
            completed, npass, ntotal = True, int(ms["p"]), int(ms["t"])
            continue
        mr = RLINE_RE.match(line)
        if mr:
            key = f'{mr["game"]}-{mr["rnd"]}'
            results[key] = {"pass": mr["p"] == "1", "fault": None if mr["fault"].startswith("none") else mr["fault"]}
    if not completed:                       # crashed — find the first GAME frame in the stack
        for line in out.splitlines():
            fm = FRAME_RE.match(line)
            if not fm:
                continue
            t = fm["type"]
            if any(t.startswith(ns) for ns in SKIP_NS):
                continue
            # compiler async state machine "<Method>d__N" on some type — nop the outer Method name
            mname = fm["method"]
            tname = t
            sm = re.match(r"<(?P<outer>[A-Za-z0-9_]+)>d__\d+", t.split("+")[-1])
            if sm:
                mname = sm["outer"]
                tname = t.split("+")[0].split(".")[-1]  # enclosing type
            else:
                tname = t.split(".")[-1].split("+")[0]
            crash = (tname, mname)
            break
    return results, completed, npass, ntotal, crash


def score(results):
    return (sum(1 for v in results.values() if v["pass"]),
            -sum(1 for v in results.values() if v["fault"]))


def regressions(base, trial):
    return sum(1 for k, v in base.items() if v["pass"] and not (trial.get(k, {}) or {}).get("pass"))


def fault_shifted(base, trial):
    """CASCADE progress: a still-failing round whose fault STRING changed (the chain moved one link forward).
    With the visual layer off each round faults through a deep chain — fixing one surfaces the next, so neither
    parity nor fault-count moves until the whole chain is patched. Accept on shift; prune drops dead links."""
    for k, bv in base.items():
        tv = trial.get(k, {}) or {}
        if tv.get("pass") or not tv.get("fault"):
            continue
        if _fault_id(tv) != _fault_id(bv):
            return True
    return False


def in_spec(spec, t, m):
    return any(e["type"] == t and e["method"] == m for e in spec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, help="battle corpus dir (JSON shared-battle records)")
    ap.add_argument("--limit", type=int, default=400, help="files per sweep (small = fast heal; validate full later)")
    ap.add_argument("--oracle-dll", default=DEFAULT_DLL)
    ap.add_argument("--out", default=os.path.join(GAME_ORACLE, "auto_patch.generated.json"))
    ap.add_argument("--passes", type=int, default=4)
    ap.add_argument("--seed", default="", help="optional existing spec json to start from")
    args = ap.parse_args()

    global DLL
    dll, corpus, spec_path = os.path.abspath(args.oracle_dll), os.path.abspath(args.corpus), os.path.abspath(args.out)
    DLL = dll
    spec = json.load(open(args.seed)) if args.seed and os.path.exists(args.seed) else []
    def write(): json.dump(spec, open(spec_path, "w"), indent=2)
    write()
    print(f"=== auto_heal ===\n  dll {dll}\n  corpus {corpus} (limit {args.limit})\n  out {spec_path}\n")

    # ── PHASE 1: crash bootstrap ──────────────────────────────────────────────────────────────────
    print("PHASE 1 — crash bootstrap (make the process complete):")
    for _ in range(80):
        out = run_sweep(dll, corpus, args.limit, spec_path)
        _, completed, npass, ntotal, crash = parse(out)
        if completed:
            print(f"  completes: {npass}/{ntotal} exact at baseline ({len(spec)} nops to survive startup)")
            break
        if not crash:
            print("  [!] crashed but no parseable game frame — dumping tail:")
            print("\n".join("    " + l for l in out.splitlines()[-12:]))
            sys.exit(1)
        t, m = crash
        if (t, m) in NEVER_PATCH:
            print(f"  [!] crash frame {t}.{m} is combat-core (never patch) — its real cure is stubbing the\n"
                  f"      VISUAL sub-call that NRE'd inside it. Dumping tail for that leaf:")
            print("\n".join("    " + l for l in out.splitlines()[-14:])); sys.exit(1)
        if in_spec(spec, t, m):
            print(f"  [!] {t}.{m} already patched yet still crashing — stop."); sys.exit(1)
        # combat-state builders: survive only (run real body, elide visual sub-calls) — never nop/stub
        if (t, m) in SURVIVE_ONLY:
            spec.append({"type": t, "method": m, "sig": "", "action": "survive"}); write()
            print(f"  + survive {t}.{m}  (crash bootstrap, combat-core)")
            continue
        # Try SURVIVE before nop. A crashing frame is not necessarily visual: gameplay-state methods like
        # BattleExecuter.CreateTempData / get_battleParamsQueue throw because a VISUAL sub-call inside them
        # NREs — blindly nopping the whole method returns null/void and CASCADES (nopped CreateTempData ->
        # the RNG queue is never built -> get_battleParamsQueue() is null -> null.Clear() NRE next frame).
        # survive runs the REAL body and elides only the visual sub-calls, so the gameplay work still happens.
        # Fall back to nop only if survive doesn't clear the crash at THIS frame (truly visual leaf method).
        chosen = None
        for action in ("survive", "nop"):
            spec.append({"type": t, "method": m, "sig": "", "action": action}); write()
            _, comp2, _, _, crash2 = parse(run_sweep(dll, corpus, args.limit, spec_path))
            if comp2 or crash2 != (t, m):           # progressed: completed, or crash moved off this frame
                chosen = action; break
            spec.pop()                              # this action didn't help here; try the next one
        if chosen is None:                          # neither moved it — keep nop as the last resort
            spec.append({"type": t, "method": m, "sig": "", "action": "nop"}); write(); chosen = "nop"
        print(f"  + {chosen} {t}.{m}  (crash bootstrap)")
    else:
        print("  [!] did not converge in 80 steps"); sys.exit(1)

    # ── PHASE 2: parity heal ──────────────────────────────────────────────────────────────────────
    print("\nPHASE 2 — parity heal (survive/nop each faulting method, keep what improves OR chains the cascade):")
    base, _, bp, bt, _ = parse(run_sweep(dll, corpus, args.limit, spec_path))
    bpass, bfault = score(base)
    print(f"  baseline {bpass}/{len(base)} exact, {-bfault} faulting")
    tried = set()
    # Iterative: re-gather the CURRENT fault methods each round (the cascade surfaces new ones as we patch),
    # rank by frequency, try to chain the most common not-yet-tried one. Bounded by max_iters.
    max_iters = args.passes * 60
    for it in range(max_iters):
        freq = collections.Counter()
        for v in base.values():
            for mm in resolve_fault(v.get("fault")):    # ordered candidates (null-source producers + leaf)
                if not mm[0].startswith("<") and mm not in tried and not in_spec(spec, *mm) \
                        and mm not in NEVER_PATCH:       # never patch pure combat-core getters / the driver
                    freq[mm] += 1
        if not freq:
            print("  no fresh fault candidates — fixpoint. Remaining distinct faults:")
            seen = {}
            for v in base.values():
                if v["fault"]:
                    seen[v["fault"]] = resolve_fault(v["fault"])
            for f, r in list(seen.items())[:6]:
                print(f"      {f}  ->  cands {r}")
            break
        (t, m), _ = freq.most_common(1)[0]
        tried.add((t, m))
        # combat-state builders get survive ONLY (nop/stub would wipe the gameplay work they do, cascading)
        actions = ("survive",) if (t, m) in SURVIVE_ONLY else ("stub", "survive", "nop")
        for action in actions:                      # stub=non-null (null sources/getters); survive keeps gameplay; nop=blank
            spec.append({"type": t, "method": m, "sig": "", "action": action}); write()
            trial, completed, _, _, _ = parse(run_sweep(dll, corpus, args.limit, spec_path))
            if not completed:
                spec.pop(); write(); continue           # this patch made it crash — reject
            # reject an action that BREAKS the patched method itself (e.g. survive -> TypeLoad on M): if M now
            # appears in more rounds' fault strings than before, this action is bad — try the next action.
            mtok = f".{m}+"
            broke_self = (sum(1 for v in trial.values() if mtok in (v.get("fault") or "")) >
                          sum(1 for v in base.values() if mtok in (v.get("fault") or "")))
            if broke_self:
                spec.pop(); write(); continue
            tp, tf = score(trial); reg = regressions(base, trial)
            improved = reg == 0 and (tp > bpass or (tp == bpass and tf > bfault))
            shifted = reg == 0 and not improved and fault_shifted(base, trial)
            if improved or shifted:
                base, bpass, bfault = trial, tp, tf
                tag = "KEEP " if improved else "CHAIN"
                print(f"    + {tag} {t}.{m} [{action}] -> {bpass}/{len(base)} exact, {-bfault} faults  (iter {it})")
                break
            spec.pop(); write()

    # ── PRUNE ────────────────────────────────────────────────────────────────────────────────────
    # Only prune once we've reached PASSING rounds — at 0 parity every chain link looks non-load-bearing
    # (removing it keeps parity at 0), so pruning would nuke the in-progress cascade. Keep the whole chain.
    if bpass == 0:
        print(f"  prune SKIPPED (parity still 0 — cascade incomplete; keeping all {len(spec)} chained patches).")
        print(f"\n=== done: {bpass}/{len(base)} exact, {-bfault} faulting; {len(spec)} patches in {spec_path} ===")
        print("  (cascade did not reach passing rounds — needs deeper candidate resolution or a wider corpus.)")
        return
    print("  prune (drop non-load-bearing patches):")
    i = 0
    while i < len(spec):
        saved = spec.pop(i); write()
        trial, completed, _, _, _ = parse(run_sweep(dll, corpus, args.limit, spec_path))
        tp, tf = score(trial) if completed else (-1, -1)
        # keep the patch if removing it crashes, drops parity, raises faults, or regresses any round
        if completed and tp >= bpass and tf >= bfault and regressions(base, trial) == 0:
            print(f"    - drop {saved['type']}.{saved['method']} [{saved['action']}]")
            base, bpass, bfault = trial, tp, tf
        else:
            spec.insert(i, saved); write(); i += 1

    print(f"\n=== done: {bpass}/{len(base)} exact, {-bfault} faulting; {len(spec)} patches in {spec_path} ===")
    print("  validate full corpus, then swap into auto_patch.json + turn the hand-fix gate off by default.")


if __name__ == "__main__":
    main()
