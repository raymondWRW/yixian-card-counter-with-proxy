# Yi Xian Oracle

A **headless battle simulator** for [Yi Xian: The Cultivation Card Game](https://store.steampowered.com/app/1948800/_/) that runs the **actual game DLL** (`DarkSun.HotUpdate.dll`) via CoreCLR's native JIT compiler. Combat results are computed by the real game logic — not a reimplementation — making them **bit-exact by construction**.

## Parity Status

| Season | Accuracy |
|--------|----------|
| Heavenly Derivation (sm9) | **6173/6173 = 100%** |
| KeYin (sm7) | **391/391 = 100%** |
| Base (sm0) | **5132/5132 = 100%** |
| Dream (sm8) | 613/615 (2 async-order residuals) |
| **Overall** | **12403/12405 = 99.97%** |

Validated against a corpus of 12,000+ recorded battle rounds across all seasons.

## How It Achieves 100% Parity

The key insight: **don't reimplement the game — run it**. The game's combat logic lives in `DarkSun.HotUpdate.dll`, a .NET assembly that Unity loads via ILRuntime (an IL interpreter). The Oracle loads that same DLL into CoreCLR, which JIT-compiles the game's IL bytecode to native machine code. Every card effect, damage calculation, buff interaction, and turn rule is the game's own code — there is nothing to get wrong.

The challenge is that the game DLL references Unity (rendering, audio, UI, animation) and various third-party libraries (DOTween, Spine, UniTask, protobuf, networking). None of those exist in a headless environment. The Oracle solves this with a three-layer architecture:

### Layer 1: Facade DLLs (Environment Stubs)

The game DLL references ~120 external assemblies. Rather than hand-stub each one, **FacadeGen** (`Oracle/FacadeGen.cs`) takes Il2CppDumper's `DummyDll` output (which has complete type/method signatures for every referenced assembly) and Cecil-rewrites every method body to return a non-null inert default (`""` for strings, `new T()` for objects, empty arrays, etc.). This produces ~120 runnable facade assemblies automatically — every type the game references is present, every method safely no-ops.

Three facades need **real behavior** and override the generated ones:
- **wProtobuf** — actual protobuf serialization/deserialization (used for configs and battle records)
- **UniTask** — async/await completion (card effects are `async UniTask` methods)
- **Cinemachine** — Transform/GameObject stubs with enough state for gameplay reads

These hand-written facades live in `UnityStubs/facades/` and take priority over the generated ones at load time.

### Layer 2: DLL Patching (Visual Suppression)

Even with facades providing non-null stubs, some visual methods cause problems headless — TypeLoadExceptions on missing Unity types, NullReferenceExceptions on scene objects that Unity never deserialized, or infinite animation loops. **DllPatcher** (`Oracle/DllPatcher.cs`) uses Cecil to pre-patch the game DLL's IL bytecode in memory before CoreCLR loads it:

- **Hand-written nop list**: A curated set of purely-visual methods (UI setters, animation players, damage popups) whose bodies are replaced with `ret`. Each was validated as non-gameplay by full-corpus sweep.
- **AutoPatch system** (`Oracle/AutoPatch.cs`): A data-driven JSON spec (`auto_patch.json`) that applies machine-generated fixes. Instead of deleting method bodies, it uses a "survive-headless" transform: restore the original IL, then neutralize only the instructions that break headless (lazy-non-null field reads, identity-elide round-trip calls). Gameplay logic survives by construction.
- **Bespoke patches**: Targeted IL rewrites for complex mechanics (KeYin card spawning, level-up modules, NetworkExtensions.Clone).

The **VisualClassifier** (`Oracle/VisualClassifier.cs`) statically analyzes every method's callgraph to classify it as GAMEPLAY (writes model state) or PURE-VISUAL (safe to suppress). This cross-checks the nop list — any method we suppress that the classifier says is GAMEPLAY is a bug.

### Layer 3: Native Execution via CoreCLR JIT

**NativeRunner** (`Oracle/NativeRunner.cs`) is the execution driver:

1. Load all game configs from protobuf `.dat` files via the game's own `ConfigLoader` (cards, buffs, talents, fates, season configs, etc.)
2. Load the Cecil-patched DLL into CoreCLR's `AssemblyLoadContext`
3. For each battle round: build both fighters via reflection (`BattleCharacterUI.InitDataBeforeBattle`), call the game's own `BattleExecuter.Execute`, read back HP/turns/winner from game memory
4. Compare against the recorded result

The game's `BattleExecuter.Execute` method drives the entire combat loop — turn alternation, card play, action-again chains, death checks, round end. We call it directly with the recorded `battleParams` (RNG sequence), so the result is deterministic and bit-exact.

## Performance

- **Single round**: ~2-4 ms (warm)
- **Full corpus sweep** (12,000+ rounds): ~11 seconds
- **Cold start** (DLL load + config deserialize): ~860 ms (paid once)

~30x faster than the old ILRuntime interpreter path (removed June 2026).

## Architecture Overview

```
Oracle/
  Program.cs          — Entry point, CLI dispatch
  NativeRunner.cs     — CoreCLR JIT loader, config setup, combat driver
  DllPatcher.cs       — Cecil IL patcher (nop visuals, bespoke rewrites)
  FacadeGen.cs        — Automatic facade generation from DummyDll
  AutoPatch.cs        — Data-driven survive-headless transforms
  OracleAnim.cs       — Animation event capture for battle viewer
  VisualClassifier.cs — Static GAMEPLAY vs PURE-VISUAL classification
  StateIndexGen.cs    — Callgraph analysis for gameplay-reads-off-visual bugs
  ProtoJson.cs        — Proto-JSON utilities
  Oracle.csproj       — .NET 8 project (needs Cecil from ILRuntime)

UnityStubs/
  facades/            — Hand-written behavior facades (UniTask, wProtobuf, etc.)
  build-facades.sh    — Builds facade DLLs from .cs sources

auto_patch.json       — Machine-generated survive-headless patch specs

scripts/
  fast_sweep.sh       — Full corpus sweep -> _results.json
  oracle_triage.py    — Classify failures, cluster by root cause, rank by leverage
  oracle_doctor.py    — Auto-detect exceptions, propose nop/stub fixes, validate
  oracle_pool.py      — Warm worker pool (persistent DLL, ~2ms per round)
  rebuild_oracle.py   — One-command game update (re-extract + regenerate + sweep)
  auto_heal.py        — Automated fix-attempt loop
  build_season_slice.py — Cross-season validation slice curation
  prune_hand_fixes.py — Identify which hand-written nops are still load-bearing
  detect_visual_gameplay_reads.py — Find "gameplay reads off inert visual" bugs
```

## Key Innovations

1. **Run the real game code** — no reimplementation means no reimplementation bugs. Card effects, damage formulas, buff interactions, turn rules are all the game's own bytecode.

2. **Automatic facade generation** — `FacadeGen.cs` algorithmically rewrites ~68,000 methods across ~120 assemblies to return non-null inert defaults. One command covers all new types when the game updates.

3. **Survive-headless transforms** (AutoPatch) — instead of deleting visual method bodies (which risks dropping gameplay), restore the original IL and neutralize only the headless-breaking instructions. Gameplay survives by construction.

4. **Static inert-visual bug detection** — `StateIndexGen.cs` walks every card/fate effect's callgraph to find the exact, finite set of gameplay reads off visual mirror objects. This closes the "whack-a-mole" bug class: instead of discovering each one via a parity failure, enumerate them all statically.

5. **Self-validating maintenance loop** — `oracle_doctor.py` detects unhandled exceptions, proposes fixes, applies them, and re-sweeps to validate. The bit-exact corpus is the oracle that accepts or rejects each fix. Near-autonomous: detect -> triage -> localize -> fix -> verify.

6. **Animation event capture** — the same headless combat run can emit structured animation events (`OracleAnim.cs`) for a web-based battle viewer, recording which character cast/attacked/took damage at each turn — parity wants visuals inert, the viewer wants them recorded; serve both from one run.

7. **Zero-effort game updates** — new cards are pure data (protobuf configs), so they work automatically. The only fragile surfaces are facade gaps (new external types — auto-detected) and the turn loop itself (rarely changes).

## Prerequisites

- .NET 8 SDK
- The game's `DarkSun.HotUpdate.dll` (extracted from the game installation via AssetRipper/Il2CppDumper)
- Game config `.dat` files (protobuf-encoded, extracted from Unity TextAssets)
- Il2CppDumper's `DummyDll` output (for facade generation)
- ILRuntime's Mono.Cecil DLLs (used only for IL patching, not interpretation)

## Quick Start

```bash
# 1. Generate facades (once per game update)
dotnet run --project Oracle -c Release -- --gen-facades

# 2. Build hand-written facade DLLs
cd UnityStubs && bash build-facades.sh && cd ..

# 3. Run a single battle (probe)
dotnet run --project Oracle -c Release

# 4. Full corpus sweep
bash scripts/fast_sweep.sh

# 5. Triage failures
python scripts/oracle_triage.py

# 6. Auto-repair detected exceptions
python scripts/oracle_doctor.py

# 7. One-command game update (re-extract + regenerate + sweep)
python scripts/rebuild_oracle.py
```

## CLI Reference

```
dotnet run --project Oracle -c Release -- [OPTIONS]

Execution modes:
  (no args)                          Sample battle probe (faults + timing)
  --records-dir <dir>                Full sweep -> _results.json
    [--shard <i> <n>]                Parallel sharding
    [--results-out <path>]           Output path
  --run-fixture <path.json>          Run one fixture
  --serve                            Warm worker mode (stdin/stdout JSON lines)
  --run-json-records <dir>           Run shared-battle JSON records
  --trace-record <path.bin> --round N  Per-turn trace of one round
  --trace-json <file> --round N      Trace one JSON record round

Tools:
  --gen-facades                      Regenerate all facade assemblies
  --ildump <Type> <Method> [hex]     Cecil IL disassembly
  --classify-visual                  Static gameplay vs visual classification
  --gen-state-index                  Generate gameplay state read index
  --recon-audit <dir>                Fighter reconstruction fidelity check

Environment variables:
  ORACLE_AUTO_PATCH=<path>           Auto-patch JSON spec (default: auto_patch.json)
  ORACLE_CAPTURE_ANIM=1             Enable animation event capture
  ORACLE_TRACE_ROUND=N              Per-turn trace for round N
  ORACLE_HAND_FIXES=0               Disable hand-written fixes (for doctor)
  ORACLE_LOAD_CONFIGS=Name,...      Load additional config tables
```

## How the Maintenance Loop Works

When a game update drops new cards or mechanics:

1. **Extract** — `rebuild_oracle.py` re-extracts `DarkSun.HotUpdate.dll` and configs from the game installation
2. **Regenerate facades** — `--gen-facades` picks up any new external types automatically
3. **Sweep** — `fast_sweep.sh` runs the full corpus and produces `_results.json`
4. **Triage** — `oracle_triage.py` clusters failures by root cause (~115 root causes from ~1785 divergences historically)
5. **Auto-repair** — `oracle_doctor.py` detects unhandled exceptions and proposes data-driven fixes
6. **Validate** — each fix is accepted only if it doesn't regress the corpus (the sweep is the oracle)

The 4 remaining failures (out of 12,405) are understood: 2 are async-order residuals in Dream season's UniTask.Delay timing, and 2 are DX sect secret-enchantment edge cases gated on per-turn ground-truth data.
