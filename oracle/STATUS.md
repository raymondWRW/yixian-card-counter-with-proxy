# Yi Xian Oracle — integration status

Goal: replace **yisim** (the JS damage reimplementation that lags game updates) with the **Oracle** —
a headless runner of the game's OWN combat code (`DarkSun.HotUpdate.dll` JIT-loaded into CoreCLR),
so damage is bit-exact and new cards work for free (they're pure config data).

## ✅ Done — engine is built, runs, and is validated on THIS game version

| Step | Result |
|------|--------|
| .NET 8 SDK | 8.0.422 installed |
| Game data extracted | `data/extracted/DarkSun.HotUpdate.dll` (6.26 MB PE) + 128 `configs/*.dat` |
| DummyDll (facade gen) | Il2CppDumper v6.7.46 → 132 assemblies |
| Cecil (IL patcher) | ILRuntime.Mono.Cecil ×3 |
| Facades | 43 hand-written + 121 generated |
| Oracle.exe | builds clean (Release) |
| **Parity (real games)** | **313/350 rounds = 89.4% bit-exact** across 40 of the user's own `recentBattleDatas`, **0 crashes**, ~13 ms/round |
| Python warm bridge | `OracleWorker` boots + handshakes in 3.4 s, then warm |

The bundled `sample_battle.bin` only scores 7/18 — it was recorded under a **different/older game version**,
so it is NOT a valid parity target for our freshly-extracted DLL. The 89.4% on the user's *current* games is the
real number. The recurring `BattleCharacterUI.LateInitAsync` NRE is **benign** (a swallowed visual late-init;
combat results are identical with or without it — proven: parity is unchanged when it's patched).

## How to build / run

```bash
python oracle/tools/extract_game_data.py     # (re-)extract DLL + configs from the install (after game updates)
bash   oracle/build.sh                        # facades → Oracle.exe → gen-facades → smoke sweep
# warm worker from Python:
python -c "import sys; sys.path.insert(0,'oracle/scripts'); from oracle_pool import OracleWorker; w=OracleWorker(); ..."
# one-shot sweep:
oracle/Oracle/bin/Release/net8.0/Oracle.exe --records-dir <dir-of-.bin> --results-out _results.json
```

Records are `Proto.RecentBattleInfo` — the SAME format as the game's `recentBattleDatas/*.bin`, so the user's
own games are directly replayable.

## ✅ yisim → Oracle integration

**复盘 review (the accuracy-critical path) — DONE & validated.**
- `proxy/oracle_sim.py` drives the warm Oracle worker. For imported (recentBattleDatas) games it
  primes the recorded round (`recent_battles.round_stat_b64`), reads sides via `describe`, then
  board-searches arrangements via the in-process `boards` batch.
- `app.py review_game` uses the Oracle for imported games (bit-exact recorded matchups, real RNG);
  folder/counter games + Oracle-unavailable fall back to yisim.
- Win/loss uses the engine's own `lifeDamage` (destiny 命), authoritative; the old `me_life`-drop
  heuristic over-flags (it disagreed with BOTH the Oracle and yisim — see `already_won`).
- Validated vs yisim: agree on clear cases (r6 won, r16 lost); on a razor-thin round the Oracle
  is authoritative (real recorded RNG vs yisim's average roll). yisim printed `[fate] unmapped
  id=266/267/268` on the same game — the exact lag the Oracle eliminates (those fates are config data).

**Live in-page damage → Oracle matchup vs the opponent's board — DONE & validated.**
- `oracle_sim.matchup(me, opp, marginal)` builds a from-scratch fixture (my board vs the opponent's)
  and returns `{win, hpDelta, turns, lifeDamage, [marginal:{slot: hp}]}` from the game's own engine.
  A live preview has no recorded RNG, so it's a real single-sample run (not bit-exact — but real
  game logic, with every card/fate handled natively).
- The live wire carries everything: `game_state.parse_game_state` already parses each player's
  talents (f200[5]/[13]) as `PlayerState.fates`; `proxy_view._oracle_side` adds characterId (pub[12]),
  realm (`realm_tier`), extraMaxHp (signed pub[4]), fateStrategies (f200[16]) and board ids, and
  attaches an `oracle` payload to `vm.me` and `vm.opponent`.
- `app.py oracle_matchup(me, opp)` runs it; `web/ui.js updateDamage` calls it when both boards are
  known and renders a WIN/LOSE pill + 命/HP/回合, falling back to yisim solo otherwise.
- Validated offline against a real capture (battle_log/2026-06-17_095012): both sides extracted with
  talents + fateStrategies from the wire, matchup ran end-to-end through `Api.oracle_matchup`
  (lose by 18 命, 11 turns). Needs a live game only for final on-screen confirmation.

Note: the separate `native_hud/` overlay (`yisim_marginal.js`) still uses yisim — it's an independent
tool; the MAIN counter app's live damage + review are both on the Oracle now.

## ⏳ Optional follow-ups

Three current yisim consumers:
1. **复盘 review** — `app.py` → `tools/yisim_review.js` (per-lost-round "was it winnable" what-if). *Best first target.*
2. **live HUD** — `native_hud/bridge/yisim_marginal.js` (node subprocess) → `HUD.SetMarginal`.
3. **in-page** — `web/yisim.bundle.js` (web/ui.js `updateDamage`).

Integration primitives (already present in the Oracle):
- `--serve` warm worker (`scripts/oracle_pool.py`, rewired to this layout) — one fixture JSON in → one result JSON out.
- Fixture schema (`RunFixtureFromText`): `{p1, p2, battleParams, mainViewId}` for an exact replay, or
  `{stat, id, deck-edits}` for the **what-if / board-search** path (what review needs).

Open design tasks:
- Build Oracle fixtures from our review payloads (`game_archive.py` `round.me`/`round.opponent`) — map our board
  representation → `p1`/`p2` proto player data. This is the main glue.
- Decide RNG handling for *hypothetical* boards (replays carry `battleParams`; what-ifs need a seed policy).
- Optional: heal 89.4% → ~100% via the bundled `oracle_triage.py` / `oracle_doctor.py` loop (clusters the ~37
  diverging rounds by root cause; the corpus is the oracle that accepts/rejects each fix).

## Packaging note
The Oracle needs the .NET 8 runtime + the bundled DLL/configs (~10 MB) at runtime — fine for the desktop app
(already ships Python + frida + node). It can't run inside a browser tab, so the in-page consumer (#3) would call
it as a local service rather than embed it.
