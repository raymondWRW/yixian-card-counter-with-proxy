// Native-JIT runner — loads the game DLL into CoreCLR (JIT-compiled to native machine code, ~30x
// faster than ILRuntime's interpreter, and BIT-EXACT by construction since it's the game's own code)
// and drives combat via plain reflection. Built ALONGSIDE the ILRuntime path (Program.cs), which stays
// the reference we validate every battle against. Milestones:
//   [M1 done] feasibility probe: raw DLL loads + combat methods JIT (Program.--native-probe).
//   [M2 done] load the DLL natively + load all game configs via reflection.
//   [M3 done] native patching (Cecil-nop visual methods so Execute doesn't NRE headless).
//   [M4 done] port BuildCharacterUI/RunRealExecute (reflection) → run a battle → read hp.
//   [M5 done] --records-dir sweep + --run-fixture parity with ILRuntime path.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.Loader;

namespace YiXianOracle;

static class NativeRunner
{
    const BindingFlags ANY_STATIC = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

    public static void Run(string[] args, string dllPath, string facadesDir, string configsDir)
    {
        Console.WriteLine("\n=== NATIVE-JIT RUNNER ===");

        // Facade set: the AUTO-GENERATED facades (facades-gen, complete coverage of every referenced type
        // with default bodies) for everything, OVERLAID by the hand-written facades for the few that need
        // real behavior (UniTask async completion, Transform/Object). Resolve by NAME (CoreCLR binds
        // strictly by version; ILRuntime by name).
        // --store points facades-gen at the version snapshot's copy (set via ORACLE_FACADES_GEN); otherwise
        // the shared build sibling of facadesDir.
        var facadesGen = Environment.GetEnvironmentVariable("ORACLE_FACADES_GEN")
            ?? Path.Combine(Path.GetDirectoryName(facadesDir)!, "facades-gen");
        // Behavior-critical facades that must keep real implementations (not generated default bodies):
        // wProtobuf does the actual proto (de)serialization for configs+records; UniTask drives async
        // completion; UnityEngine.CoreModule has Transform/Object/GameObject semantics combat reads.
        // (NetworkExtensions.Clone<T>'s proto round-trip goes through DarkSun.Utility's ProtobufParser, whose
        // facades-gen stub returns a null decode stream -> Clone NREs -> Card_19/126/326.UpdateCardInfo's
        // evolution is silently swallowed (Sword Embryo plays at BASE). We can't override the whole
        // DarkSun.Utility assembly (the hand-written one is missing types like TencentClsLogListener); instead
        // DllPatcher.PatchNetworkExtensionsClone rewrites Clone to a direct WriteTo/MergeFrom round-trip.)
        var overrideNames = new System.Collections.Generic.HashSet<string> { "wProtobuf", "UniTask", "Cinemachine" };
        string? Pick(string name)
        {
            if (overrideNames.Contains(name)) { var h = Path.Combine(facadesDir, name + ".dll"); if (File.Exists(h)) return h; }
            var g = Path.Combine(facadesGen, name + ".dll"); if (File.Exists(g)) return g;
            var h2 = Path.Combine(facadesDir, name + ".dll"); return File.Exists(h2) ? h2 : null;
        }
        // Resolve by NAME, but FIRST return an already-loaded copy. The game references specific assembly
        // VERSIONS (e.g. DOTween 1.0.0.0); our facades are 0.0.0.0. When the version differs, CoreCLR fires
        // Resolving even though a same-named assembly is loaded — re-loading the facade-gen file from disk
        // would put TWO same-named assemblies in one ALC (FileLoadException). Returning the loaded copy
        // makes resolution version-agnostic and idempotent (bin hand-written / first-loaded wins).
        AssemblyLoadContext.Default.Resolving += (ctx, name) =>
        {
            var existing = ctx.Assemblies.FirstOrDefault(a => a.GetName().Name == name.Name);
            if (existing != null) return existing;
            var p = Pick(name.Name!); return p != null ? ctx.LoadFromAssemblyPath(p) : null;
        };
        foreach (var n in overrideNames) { var p = Path.Combine(facadesDir, n + ".dll"); if (File.Exists(p)) try { AssemblyLoadContext.Default.LoadFromAssemblyPath(p); } catch { } }
        if (Directory.Exists(facadesGen))
            foreach (var dll in Directory.GetFiles(facadesGen, "*.dll"))
            {
                var bn = Path.GetFileNameWithoutExtension(dll);
                if (overrideNames.Contains(bn)) continue;
                // facades-gen now emits NON-NULL inert returns (FacadeGen.EmitNonNullRef): string -> "",
                // arrays/collections/objects -> empty/fresh. StringExtensions.Translate etc. no longer return
                // null, so the old per-facade null-patch (PatchFacadeTranslateReturns) is unnecessary.
                try { AssemblyLoadContext.Default.LoadFromAssemblyPath(dll); }
                catch { }
            }
        Console.WriteLine($"  facades: generated ({facadesGen}) + {overrideNames.Count} hand-written behavior overrides");

        // 1. Cecil-pre-patch the game DLL's visual methods (CoreCLR has no AbsorbVisualNulls hook), then
        //    load the patched bytes natively. The patcher resolves types from the COMPLETE generated
        //    facades so the module writes back cleanly (the old deprecated path failed on LanguageType).
        Assembly game;
        // Default-load the accepted auto-patch spec (oracle_doctor's durable, sweep-validated fixes) when the
        // env override is unset, so the loop's accepted gains apply to every normal run — not just doctor runs.
        if (Environment.GetEnvironmentVariable("ORACLE_AUTO_PATCH") == null)
        {
            var defSpec = Path.GetFullPath(Path.Combine(facadesDir, "..", "..", "..", "auto_patch.json"));
            if (File.Exists(defSpec)) Environment.SetEnvironmentVariable("ORACLE_AUTO_PATCH", defSpec);
        }
        var patched = DllPatcher.PatchForNative(File.ReadAllBytes(dllPath), facadesGen, facadesDir);
        using (var ps = new MemoryStream(patched))
            game = AssemblyLoadContext.Default.LoadFromStream(ps);
        Console.WriteLine($"  loaded {game.GetName().Name} natively (visual-patched)");

        // 2. Point the game's ConfigLoader at our .dat files (via the Addressables facade static) and load
        //    every config — mirrors Program.cs's ILRuntime config setup, but with plain reflection.
        UnityEngine.AddressableAssets.Addressables.ConfigDirectory = configsDir;
        Console.WriteLine($"  config dir: {configsDir} (CardConfig.dat exists: {File.Exists(Path.Combine(configsDir, "CardConfig.dat"))})");

        // Animator factory: build the CHARACTER-SPECIFIC animator type (CharacterBattleAnimator_<charId>) so
        // game code that casts `src.animator as CharacterBattleAnimator_<id>` and derefs it doesn't NRE
        // headless (e.g. Li Man's SwitchJiaShi). GetUninitializedObject (no ctor) — its methods are nopped.
        var animBaseT = game.GetType("CharacterBattleAnimator");
        if (animBaseT != null)
        {
            Func<object, object> animFactory = pub =>
            {
                int id = 0; try { id = Convert.ToInt32(NGet(pub, "characterId")); } catch { }
                object anim;
                var t = id != 0 ? game.GetType($"CharacterBattleAnimator_{id}") : null;
                anim = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(t ?? animBaseT);
                // Populate the animator's gameplay-read fields: cards/fates branch on animator.charId and
                // animator.skinNumber (e.g. Card_12 "Only Traces"). GetUninitializedObject leaves them 0 ->
                // those branches read wrong -> silent value divergence. Seed them from publicData.
                try { NSet(anim, "charId", id); } catch { }
                try { NSet(anim, "skinNumber", Convert.ToInt32(NGet(pub, "skinNumber") ?? 0)); } catch { }
                return anim;
            };
            SetStatic(game.GetType("BattleExecuter")!, "s_OracleAnimatorFactory", animFactory);
        }

        var cfgMgr = game.GetType("ConfigManager") ?? throw new Exception("ConfigManager not found");
        // (configTypeName, ownerTypeName, staticFieldName). Keyed dicts (cardConfigDict) are built by
        // the game's own loader on first access; here we set the raw static lists the combat path reads.
        // IMPORTANT: talentResonanceConfigs, keYinCardConfigs, and npcConfigs do NOT live on ConfigManager
        // — they're on TalentResonancePanel, KeYinCardFactory, and ConfigManager respectively.
        // LevelConfig is accessed only via levelConfigDict (built below) — no separate list needed.
        var configs = new (string type, string ownerType, string field)[]
        {
            ("CardConfig",             "ConfigManager",        "s_CardConfigs"),
            ("TalentConfig",           "ConfigManager",        "talentConfigs"),
            ("BuffConfig",             "ConfigManager",        "buffConfigs"),
            ("CardFXConfig",           "ConfigManager",        "cardFXConfigs"),
            ("CharacterConfig",        "ConfigManager",        "s_CharacterConfigs"),
            ("FateStrategyConfig",     "ConfigManager",        "s_FateStrategyConfigs"),
            ("SeasonConfig",           "ConfigManager",        "s_SeasonConfigs"),
            ("SectTalentConfig",       "ConfigManager",        "s_OriginalSectTalentConfs"),
            // These three are on separate factory/panel types (NOT ConfigManager):
            ("TalentResonanceConfig",  "TalentResonancePanel", "s_ResonanceTalentConfigs"),
            ("KeYinCardConfig",        "KeYinCardFactory",     "s_KeYinCardConfigs"),
            // NpcConfig: GetNpcConfig does npcConfigs.Find(...) during character setup; unloaded -> NRE.
            ("NpcConfig",              "ConfigManager",        "npcConfigs"),
        };
        int ok = 0;
        foreach (var (type, ownerType, field) in configs)
        {
            try
            {
                var list = LoadConfigList(game, type, configsDir);
                int n = (list as System.Collections.ICollection)?.Count ?? -1;
                var ownerT = game.GetType(ownerType) ?? throw new Exception($"owner type {ownerType} not found");
                if (SetStatic(ownerT, field, list)) { ok++; Console.WriteLine($"    {type,-22} -> {ownerType}.{field} ({n})"); }
                else Console.WriteLine($"    {type,-22} -> {ownerType}.{field}: STATIC NOT FOUND ({n} loaded)");
            }
            catch (Exception e) { Console.WriteLine($"    {type,-22}: LOAD FAIL {(e.InnerException ?? e).Message}"); }
        }
        Console.WriteLine($"  configs loaded: {ok}/{configs.Length}");

        // AUTO-LOAD every remaining <Name>.dat into its backing static List<Name> field (found by reflection),
        // generalizing the hardcoded list so NO combat read of any season/character's config table hits an
        // empty list. Critically covers the HD/Fate-Strategy season tables (Divination*/FateBranch*) and any
        // future config a game update adds — automatic, no per-config hand-coding. Additive; the canonical
        // fields above win (skipped here). Sweep-validated (HD must stay 100%).
        LoadAllConfigsAuto(game, configsDir, new System.Collections.Generic.HashSet<string>(configs.Select(c => c.type)));

        // 3. Build the keyed dicts + buff-category map the combat path reads (the game builds these from
        //    the lists at init via compiler-gen code we bypass; replicate them — same as Program.cs's
        //    LoadConfigInto + BuildBuffCategoryMap, but native reflection).
        BuildDict(cfgMgr, "cardConfigDict", LoadConfigList(game, "CardConfig", configsDir), "id");
        BuildDict(cfgMgr, "levelConfigDict", LoadConfigList(game, "LevelConfig", configsDir), "level");
        BuildBuffCategoryMap(cfgMgr, LoadConfigList(game, "BuffConfig", configsDir));
        // Pre-build OpenManager.s_OpenDict (OpenType -> List<OpenConfig>) from OpenConfig.dat so the real
        // IsOpen/GetOpenConfig/get_openDict path replays the EXACT recorded feature flags. (Hardcoding
        // IsOpen=true loses accuracy on records where some flags were closed — it regressed the suite.)
        BuildOpenDict(game, LoadConfigList(game, "OpenConfig", configsDir));
        // CharacterAnimClipConfig: the combat Attack path reads ConfigManager.charAnimClipDict via
        // GetCharacterAnimClipConfig; that table is unloaded by default -> returns null -> the
        // <Attack>d__116 NRE (IL_01E2) that ABORTED attacks (6 Sigil rounds) so their damage never applied.
        // Loading it (grouped by charId) clears those faults and the attacks land. Found via `ildump
        // configaudit` (21 combat refs, unloaded); validated +4 Sigil rounds, 0 regression on HD.
        BuildGroupedDict(cfgMgr, "charAnimClipDict", LoadConfigList(game, "CharacterAnimClipConfig", configsDir), "charId");

        // Generic data-driven EXTRA config loads (env ORACLE_LOAD_CONFIGS; inert if unset), additive on top
        // of the core tables above. A combat lookup of an UNLOADED config table returns null/0 -> NRE or
        // wrong damage (find them with `ildump configaudit`); this lets oracle_doctor try "load <config>"
        // candidates WITHOUT recompiling. Comma-list of entries:
        //   "Name"                          -> load Name.dat into an auto-found static List<Name> field
        //   "Name@DictField/keyField"       -> also build ConfigManager dict (Dictionary<key,Name>)
        //   "Name@DictField/keyField*"      -> build a GROUPED dict (Dictionary<key,List<Name>>)   (* grouped)
        // e.g. ORACLE_LOAD_CONFIGS=CharacterAnimClipConfig@charAnimClipDict/charId*
        var extraCfgs = Environment.GetEnvironmentVariable("ORACLE_LOAD_CONFIGS");
        if (!string.IsNullOrEmpty(extraCfgs))
            foreach (var spec in extraCfgs.Split(',', StringSplitOptions.RemoveEmptyEntries))
            {
                var at = spec.Split('@');
                var cname = at[0].Trim();
                try
                {
                    var clist = LoadConfigList(game, cname, configsDir);
                    int cn = (clist as System.Collections.ICollection)?.Count ?? -1;
                    bool placedList = TryPlaceConfigList(game, cname, clist);
                    string dictInfo = "-";
                    if (at.Length >= 2 && at[1].Contains('/'))
                    {
                        bool grouped = at[1].TrimEnd().EndsWith("*");
                        var dk = at[1].TrimEnd().TrimEnd('*').Split('/');
                        if (grouped) BuildGroupedDict(cfgMgr, dk[0].Trim(), clist, dk[1].Trim());
                        else BuildDict(cfgMgr, dk[0].Trim(), clist, dk[1].Trim());
                        dictInfo = dk[0].Trim() + (grouped ? "*" : "");
                    }
                    Console.WriteLine($"    [extra-config] {cname} ({cn}) list={placedList} dict={dictInfo}");
                }
                catch (Exception e) { Console.WriteLine($"    [extra-config] {cname}: FAIL {(e.InnerException ?? e).Message}"); }
            }

        // Sanity: can we read a known card config back (proves the loader + statics work natively)?
        try
        {
            var loader = game.GetType("ConfigLoader")!;
            var find = game.GetType("CardFactory")?.GetMethod("FindCardConfig", BindingFlags.Public | BindingFlags.Static);
            if (find != null)
            {
                var cfg = find.Invoke(null, new object[] { 1000019 });   // Giant Whale Spirit Sword base
                var id = cfg?.GetType().GetField("id")?.GetValue(cfg);
                Console.WriteLine($"  FindCardConfig(1000019).id = {id}  {(Convert.ToInt32(id ?? 0) == 1000019 ? "[OK native config read]" : "[MISMATCH]")}");
            }
        }
        catch (Exception e) { Console.WriteLine($"  config read-back FAIL: {(e.InnerException ?? e).Message}"); }

        // 3b. Dump a config table as JSON: --dump-config <Name> [--out <path>]. Loads <Name>.dat via the
        //     game's own ConfigLoader and emits every row as ProtoJson (1:1 field names) — for reading
        //     game data (e.g. FateStrategyConfig = 天衍 derivations: countParam / otherParams per id).
        {
            var dci = Array.IndexOf(args, "--dump-config");
            if (dci >= 0 && dci + 1 < args.Length)
            {
                var cname = args[dci + 1];
                var list = LoadConfigList(game, cname, configsDir);
                var arr = new System.Text.Json.Nodes.JsonArray();
                if (list is System.Collections.IEnumerable en)
                    foreach (var row in en) arr.Add(ProtoJson.ToNode(row));
                var json = arr.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true });
                var oi = Array.IndexOf(args, "--out");
                if (oi >= 0 && oi + 1 < args.Length) { File.WriteAllText(args[oi + 1], json); Console.WriteLine($"wrote {arr.Count} {cname} rows -> {args[oi + 1]}"); }
                else Console.WriteLine(json);
                Console.Out.Flush(); Environment.Exit(0);
            }
        }

        // 4. Records-dir sweep: --records-dir <dir> [--shard <idx> <count>] [--results-out <path>]
        //    Same format/semantics as the ILRuntime sweep in Program.cs lines 318-399.
        {
            var sdi = Array.IndexOf(args, "--records-dir");
            if (sdi >= 0 && sdi + 1 < args.Length)
            {
                RunRecordsSweep(game, args, configsDir);
                Console.Out.Flush(); Environment.Exit(0);
            }
        }

        // 4b. Reconstruction-fidelity audit: --recon-audit <recordsDir>. For every fighter in every round,
        //     build it via BuildCharacterUI and check that NO usedCard silently dropped from the deck (a
        //     null/unresolved cardConfig → a short deck → silent combat divergence). Aggregates + prints
        //     per-fighter drops as JSON lines so failures can be correlated with the parity sweep.
        {
            var rai = Array.IndexOf(args, "--recon-audit");
            if (rai >= 0 && rai + 1 < args.Length)
            {
                RunReconAudit(game, args[rai + 1]);
                Console.Out.Flush(); Environment.Exit(0);
            }
        }

        // 4c. Run shared-battle JSON records: --run-json-records <dir> [--limit N]. Each <id>_pN.json is a
        //     RecentBattleInfo in JSON ({code,data}); build the proto by reflection and run its combat rounds.
        {
            var jri = Array.IndexOf(args, "--run-json-records");
            if (jri >= 0 && jri + 1 < args.Length)
            {
                int lim = 0; var li = Array.IndexOf(args, "--limit");
                if (li >= 0 && li + 1 < args.Length) int.TryParse(args[li + 1], out lim);
                RunJsonRecords(game, args[jri + 1], configsDir, lim);
                Console.Out.Flush(); Environment.Exit(0);
            }
        }
        // 4d. Trace one round of a JSON shared-battle record: --trace-json <file> --round <N>.
        {
            var tji = Array.IndexOf(args, "--trace-json");
            if (tji >= 0 && tji + 1 < args.Length)
            {
                int rnd = 0; var rio = Array.IndexOf(args, "--round"); if (rio >= 0 && rio + 1 < args.Length) int.TryParse(args[rio + 1], out rnd);
                RunTraceJson(game, args[tji + 1], configsDir, rnd);
                Console.Out.Flush(); Environment.Exit(0);
            }
        }

        // 4e. Warm worker: --serve. The DLL+configs are already loaded (the ~860ms cold-start is paid ONCE);
        //     now read one fixture JSON per line from stdin and emit one result JSON per line on stdout
        //     (~2ms each — no per-call process/JIT/config reload). Pin a version with --store. A line of
        //     `quit` or EOF ends the loop. This is the engine behind the warm-worker pool (oracle_pool.py).
        if (args.Contains("--serve")) { RunServe(game, configsDir); Console.Out.Flush(); Environment.Exit(0); }

        // 5. Single-fixture run: --run-fixture <path.json>
        {
            var rfi = Array.IndexOf(args, "--run-fixture");
            if (rfi >= 0 && rfi + 1 < args.Length)
            {
                RunNativeFixture(game, args[rfi + 1]);
                Console.Out.Flush(); Environment.Exit(0);
            }
        }

        // 5a. Enrich fixtures with the raw round-stat proto blob: --enrich-fixtures <recordsDir> <fixturesDir>.
        {
            var efi = Array.IndexOf(args, "--enrich-fixtures");
            if (efi >= 0 && efi + 2 < args.Length)
            {
                EnrichFixtures(game, args[efi + 1], args[efi + 2]);
                Console.Out.Flush(); Environment.Exit(0);
            }
        }

        // 5b. Per-turn trace of ONE record round straight from the .bin (debug parity divergences):
        //     --trace-record <path.bin> --round <N>. Runs RunOneRound (real record input, no fragile
        //     fixture reconstruction) with s_OracleTrace on and prints the per-turn mutation log + the
        //     record's own stored per-turn log (rsObj.log) so they can be diffed turn-by-turn.
        {
            var tri = Array.IndexOf(args, "--trace-record");
            if (tri >= 0 && tri + 1 < args.Length)
            {
                int rnd = 0; var rio = Array.IndexOf(args, "--round");
                if (rio >= 0 && rio + 1 < args.Length) int.TryParse(args[rio + 1], out rnd);
                RunTraceRecord(game, args[tri + 1], rnd);
                Console.Out.Flush(); Environment.Exit(0);
            }
        }

        // M4 probe — run one battle natively (sample_battle round 1) to report faults + timing.
        try
        {
            var sampleBin = Path.Combine(Path.GetDirectoryName(dllPath)!, "..", "..", "tools", "game-oracle", "Oracle", "sample_battle.bin");
            sampleBin = File.Exists(sampleBin) ? sampleBin : Path.Combine(AppContext.BaseDirectory, "sample_battle.bin");
            RunBattleProbe(game, sampleBin);
        }
        catch (Exception e) { Console.WriteLine($"  [M4 battle probe] {(e.InnerException ?? e).GetType().Name}: {(e.InnerException ?? e).Message}"); }

        Console.WriteLine("=== native runner: M1-M5 done ===");
    }

    // ── Sweep: iterate every *.bin in dir (sharded), run each round, write _results.json ──────────
    static void RunRecordsSweep(Assembly game, string[] args, string configsDir)
    {
        var dir = args[Array.IndexOf(args, "--records-dir") + 1];
        var recFiles = Directory.GetFiles(dir, "*.bin").OrderBy(f => f).ToList();
        { var shi = Array.IndexOf(args, "--shard");
          if (shi >= 0 && shi + 2 < args.Length
              && int.TryParse(args[shi + 1], out var sIdx) && int.TryParse(args[shi + 2], out var sCnt) && sCnt > 0)
              recFiles = recFiles.Where((_, i) => i % sCnt == sIdx).ToList(); }
        string? resultsOut = null;
        { var roi = Array.IndexOf(args, "--results-out"); if (roi >= 0 && roi + 1 < args.Length) resultsOut = args[roi + 1]; }
        // --only-version <v>: skip any replay whose embedded RecentBattleInfo.version != v. Used by the
        // version-routed sweep so a replay is ONLY ever run against the game version it was recorded under
        // (this --store snapshot's version), never a newer build that would falsely diverge it.
        string? onlyVersion = null;
        { var ovi = Array.IndexOf(args, "--only-version"); if (ovi >= 0 && ovi + 1 < args.Length) onlyVersion = args[ovi + 1]; }
        var resultsMap = resultsOut != null ? new Dictionary<string, object>() : null;
        int gTot = 0, gPass = 0, gCrashRounds = 0, fullRecords = 0, crashRecords = 0, errRecords = 0, skippedRecords = 0;
        var swAll = System.Diagnostics.Stopwatch.StartNew();
        Console.WriteLine($"\n=== NATIVE SWEEP {recFiles.Count} records in {dir} ===");

        // BattleManager replay singleton — set up ONCE, reused per round (mirrors RunBattleProbe). Without
        // this, BattleManager.Instance is null and every Execute crashes immediately (turns=0) — which is
        // why the sweep reported 0/N all-crashed while the sample probe ran fine.
        var bm = New(game.GetType("BattleManager")!);
        SetStatic(game.GetType("BattleManager")!, "Instance", bm);
        NSet(bm, "currentGameStatus", New(game.GetType("Proto.GameStatus")!));
        NSet(bm, "currentScene", Enum.Parse(game.GetType("SceneType")!, "斗法阶段"));
        NSet(bm, "replaying", true);

        var cfgMgr = game.GetType("ConfigManager")!;
        foreach (var rf in recFiles)
        {
            try
            {
                // PER-RECORD STATE RESET: combat can mutate shared config objects in place (special-card
                // evolution mutates a CardConfig, talent/buff level-ups mutate their configs), and that leaks
                // into later records in this single-process sweep — a record that passes in ISOLATION fails
                // after others run (confirmed: dvmin0e-r09 71/17 isolated vs 36/26 in-corpus). Reload pristine
                // configs before each record so every record starts exactly as the real game starts a match.
                var freshCards = LoadConfigList(game, "CardConfig", configsDir);
                SetStatic(cfgMgr, "s_CardConfigs", freshCards);
                BuildDict(cfgMgr, "cardConfigDict", freshCards, "id");
                SetStatic(cfgMgr, "talentConfigs", LoadConfigList(game, "TalentConfig", configsDir));
                SetStatic(cfgMgr, "buffConfigs", LoadConfigList(game, "BuffConfig", configsDir));
                var rbi = New(game.GetType("Proto.RecentBattleInfo")!);
                var ms2 = new wProtobuf.MessageStream(File.ReadAllBytes(rf));
                game.GetType("Proto.RecentBattleInfo")!.GetMethod("MergeFrom", ANY)!.Invoke(rbi, new object[] { ms2 });
                if (onlyVersion != null && (NGet(rbi, "version") as string) != onlyVersion) { skippedRecords++; continue; }
                var roundStats = (System.Collections.IList)NGet(rbi, "roundStats")!;
                // Sort rounds ascending so early (smaller deck) rounds come first.
                var rl = new List<(int rnd, object rsObj)>();
                foreach (var rs in roundStats) rl.Add((Convert.ToInt32(NGet(rs, "round") ?? 0), rs));
                rl.Sort((a, b) => a.rnd.CompareTo(b.rnd));
                int rPass = 0, rCrash = 0;
                foreach (var (rnd, rsObj) in rl)
                {
                    int rec = Convert.ToInt32(NGet(rsObj, "hpDelta") ?? 0);
                    int recTurns = Convert.ToInt32(NGet(rsObj, "huiHeCount") ?? 0);
                    int recLife = Convert.ToInt32(NGet(rsObj, "lifeDamage") ?? 0);
                    // Restore this round's deck CardConfigs before running — rounds within a record otherwise
                    // inherit an earlier round's special-card-evolution mutation (the per-record reset above
                    // only covers the FIRST round). Cheap in-memory targeted restore.
                    RestoreDeckConfigs(game, cfgMgr, configsDir, rsObj);
                    double roundMs; string? faultInfo;
                    var (lhp, rhp, turns) = RunOneRound(game, rsObj, rnd, out faultInfo, out roundMs);
                    int simDelta = lhp - rhp;
                    bool cPass = simDelta == rec && turns == recTurns;
                    if (cPass) rPass++;
                    if (turns <= 2 && recTurns > 3) rCrash++;
                    resultsMap?.Add($"{Path.GetFileNameWithoutExtension(rf)}-r{rnd:00}", new
                    {
                        pass = cPass, destinyFlagged = cPass && (lhp == -999 || rhp == -999 ? false : lhp - rhp != rec),
                        simHpDelta = simDelta, recHpDelta = rec, simTurns = turns, recTurns,
                        simLife = s_LastLifeDamage, recLife,
                        fault = faultInfo,   // parity diagnosis: the first un-nopped method that threw (null = clean run)
                    });
                }
                gTot += rl.Count; gPass += rPass; gCrashRounds += rCrash;
                if (rl.Count > 0 && rPass == rl.Count) fullRecords++;
                if (rl.Count > 0 && rCrash >= rl.Count) crashRecords++;
                Console.WriteLine($"  {Path.GetFileName(rf)}: {rPass}/{rl.Count}{(rCrash > 0 ? $"  ({rCrash} crash)" : "")}");
            }
            catch (Exception ex) { errRecords++; Console.WriteLine($"  {Path.GetFileName(rf)}: ERROR {(ex.InnerException ?? ex).GetType().Name}: {(ex.InnerException ?? ex).Message}"); }
            // Incremental flush after each record.
            if (resultsOut != null && resultsMap != null && resultsMap.Count > 0)
                try { File.WriteAllText(resultsOut, System.Text.Json.JsonSerializer.Serialize(resultsMap)); } catch { }
        }
        if (resultsOut != null && resultsMap != null)
        {
            File.WriteAllText(resultsOut, System.Text.Json.JsonSerializer.Serialize(resultsMap));
            Console.WriteLine($"  wrote {resultsMap.Count} round results to {resultsOut}");
        }
        double pct = gTot > 0 ? 100.0 * gPass / gTot : 0;
        Console.WriteLine($"\n=== NATIVE SWEEP: {gPass}/{gTot} rounds exact across {recFiles.Count - skippedRecords} records " +
            $"({fullRecords} fully-exact, {crashRecords} fully-crashed, {gCrashRounds} crash-aborted rounds, {errRecords} errors" +
            $"{(onlyVersion != null ? $", {skippedRecords} skipped (version != {onlyVersion})" : "")}) " +
            $"in {swAll.Elapsed.TotalSeconds:F0}s — {pct:F1}% ===");
    }

    // ── Trace one record round from .bin with the per-turn mutation hook (debug parity divergences) ──
    static void RunTraceRecord(Assembly game, string binPath, int round)
    {
        var rbi = New(game.GetType("Proto.RecentBattleInfo")!);
        game.GetType("Proto.RecentBattleInfo")!.GetMethod("MergeFrom", ANY)!
            .Invoke(rbi, new object[] { new wProtobuf.MessageStream(File.ReadAllBytes(binPath)) });
        var roundStats = (System.Collections.IList)NGet(rbi, "roundStats")!;
        object? rsObj = null;
        foreach (var rs in roundStats) if (Convert.ToInt32(NGet(rs!, "round") ?? -1) == round) { rsObj = rs; break; }
        if (rsObj == null) { Console.WriteLine($"  round {round} not found ({roundStats.Count} rounds)"); return; }

        // BattleManager replay singleton (same as the sweep).
        var bm = New(game.GetType("BattleManager")!);
        SetStatic(game.GetType("BattleManager")!, "Instance", bm);
        NSet(bm, "currentGameStatus", New(game.GetType("Proto.GameStatus")!));
        NSet(bm, "currentScene", Enum.Parse(game.GetType("SceneType")!, "斗法阶段"));
        NSet(bm, "replaying", true);

        int recHp = Convert.ToInt32(NGet(rsObj, "hpDelta") ?? 0);
        int recTurns = Convert.ToInt32(NGet(rsObj, "huiHeCount") ?? 0);
        Console.WriteLine($"\n=== TRACE {Path.GetFileNameWithoutExtension(binPath)} round {round}  (recorded hpDelta={recHp}, turns={recTurns}) ===");
        // CLONE TEST (ORACLE_DIAG_CLONE=1): clone a CardConfig via the patched NetworkExtensions.Clone<T>
        // and report whether it's faithful (attack/otherParams preserved) or throws — Card_19/126/326
        // UpdateCardInfo does FindCardConfig(id).Clone() then mutates it; a broken Clone => card stuck base.
        if (Environment.GetEnvironmentVariable("ORACLE_DIAG_CLONE") == "1")
        {
            try
            {
                var ccType = game.GetType("Proto.CardConfig") ?? game.GetType("CardConfig")!;
                var cfg = game.GetType("CardFactory")!.GetMethod("FindCardConfig", BindingFlags.Public | BindingFlags.Static)!.Invoke(null, new object[] { 19 });
                var cloneM = game.GetType("NetworkExtensions")!.GetMethods(ANY).First(m => m.Name == "Clone" && m.IsGenericMethodDefinition && m.GetParameters().Length == 1).MakeGenericMethod(ccType);
                var clone = cloneM.Invoke(null, new[] { cfg });
                Console.WriteLine($"  [clone test] orig: attack={NGet(cfg!, "attack")} otherParams={(NGet(cfg!, "otherParams") as System.Collections.IList)?.Count}  ==>  clone: {(clone == null ? "NULL" : $"attack={NGet(clone, "attack")} otherParams={(NGet(clone, "otherParams") as System.Collections.IList)?.Count} name={NGet(clone, "name")}")}");
            }
            catch (Exception ce) { var ix = ce.InnerException ?? ce; Console.WriteLine($"  [clone test] THREW {ix.GetType().Name}: {ix.Message.Split('\n')[0]}"); foreach (var f in new System.Diagnostics.StackTrace(ix, false).GetFrames()?.Take(6) ?? Array.Empty<System.Diagnostics.StackFrame>()) Console.WriteLine($"      at {f.GetMethod()?.DeclaringType?.Name}.{f.GetMethod()?.Name}+IL_{f.GetILOffset():X4}"); }
            // Are the embryo's talent configs loaded? UpdateCardInfo derefs GetTalentConfig(X).otherParams.
            var gtc = game.GetType("ConfigManager")!.GetMethod("GetTalentConfig", BindingFlags.Public | BindingFlags.Static);
            foreach (var tid in new[] { 92, 10093, 20093, 20094, 20095, 30096 })
            { try { var tc = gtc!.Invoke(null, new object[] { tid }); Console.WriteLine($"      GetTalentConfig({tid}) = {(tc == null ? "NULL" : "ok otherParams=" + ((NGet(tc, "otherParams") as System.Collections.IList)?.Count))}"); } catch (Exception e) { Console.WriteLine($"      GetTalentConfig({tid}) threw {(e.InnerException ?? e).GetType().Name}"); } }
            // Does StringExtensions.Translate return null? UpdateCardInfo does Translate(key).Replace(..) ->
            // if null, NRE aborts the method BEFORE the InitData commit -> evolved config discarded.
            try { var seT = game.GetType("StringExtensions"); var tr = seT?.GetMethods(ANY).FirstOrDefault(m => m.Name == "Translate" && m.GetParameters().Length >= 1 && m.GetParameters()[0].ParameterType == typeof(string)); var r = tr?.Invoke(null, tr.GetParameters().Select((p, i) => i == 0 ? (object)"TalentCardDesc_20094" : null).ToArray()); Console.WriteLine($"      StringExtensions.Translate(\"TalentCardDesc_20094\") = {(r == null ? "NULL  <== the abort source" : "\"" + r + "\"")}"); } catch (Exception e) { Console.WriteLine($"      Translate test threw {(e.InnerException ?? e).GetType().Name}"); }
        }
        // STATE-DIFF: dump each fighter's RESOLVED deck (card id -> cardConfig attack/def/level) right after
        // native builds it. The record's p1/p2 is the complete deterministic input, so if native builds a
        // card at the wrong stats/level (e.g. the Sword Embryo not evolved, a fate-upgraded card at base),
        // it shows here — the divergence is state reconstruction, and this makes it visible vs expectation.
        foreach (var who in new[] { "p1", "p2" })
        {
            var pd = NGet(rsObj, who); if (pd == null) continue;
            var pub0 = NGet(pd, "publicData");
            var lrd0 = NGet(pub0!, "lastRoundData");
            Console.WriteLine($"  --- deck {who} (char {NGet(pub0!, "characterId")}, talents {string.Join(",", ((NGet(pub0!, "talents") as System.Collections.IList)?.Cast<object>() ?? Enumerable.Empty<object>()))}) ---");
            Console.WriteLine($"      [nulls] pub.talents={(NGet(pub0!,"talents")==null?"NULL":"ok")} pub.talentTempDatas={(NGet(pub0!,"talentTempDatas")==null?"NULL":"ok")} pub.cardSkins={(NGet(pub0!,"cardSkins")==null?"NULL":"ok")} pub.lastRoundData={(lrd0==null?"NULL":"ok")} lrd.talentTempDatas={(lrd0!=null&&NGet(lrd0,"talentTempDatas")!=null?"ok":"NULL")}");
            try
            {
                var ui = BuildCharacterUI(game, pd);
                var items = NGet(ui, "battleCardItems") as System.Collections.IList;
                if (items != null) foreach (var ci in items)
                {
                    var cfg = NGet(ci!, "cardConfig"); if (cfg == null) continue;
                    Console.WriteLine($"      grid{NGet(ci, "gridNumber")} id={NGet(cfg, "id")} atk={NGet(cfg, "attack")} def={NGet(cfg, "def")} lvl={NGet(cfg, "level")} jianYi={NGet(cfg, "jianYi")}");
                }
            }
            catch (Exception e) { Console.WriteLine($"      deck-dump err: {(e.InnerException ?? e).Message}"); }
        }
        // RunOneRound has a built-in per-turn tracer (L/R side + hp-before) gated on env ORACLE_TRACE_ROUND;
        // enable it for this round instead of a separate hook (which RunOneRound would otherwise clobber).
        Environment.SetEnvironmentVariable("ORACLE_TRACE_ROUND", round.ToString());
        var (lhp, rhp, turns) = RunOneRound(game, rsObj, round, out var fault, out _);
        Environment.SetEnvironmentVariable("ORACLE_TRACE_ROUND", null);
        Console.WriteLine($"=== native: leftHp={lhp} rightHp={rhp} hpDelta={lhp - rhp} turns={turns}  (rec {recHp}/{recTurns})  {(fault != null ? "FAULT: " + fault : "")} ===");
        // DIAG: fate 197 (Hexagrams Explain) gate — CardActionBase.YiGuaZiJieCheck(bpData) returns true iff
        // talents.Contains(197) AND exactly 2 of the 8 hexagram cards are in lastRoundData.usedCards. Print
        // the real method's result + a manual recompute per player, to see if native's gate is correct.
        try
        {
            var cab = game.GetType("CardActionBase");
            var yi = cab?.GetMethod("YiGuaZiJieCheck", new[] { game.GetType("Proto.BattlePlayerData")! });
            var hexCards = new HashSet<int> { 4000001, 4000002, 4000003, 4000015, 4000016, 4000025, 4000034, 4000026 };
            var getBase = game.GetType("CardFactory")!.GetMethod("GetBaseCardId", BindingFlags.Public | BindingFlags.Static);
            foreach (var who in new[] { "p1", "p2" })
            {
                var pd = NGet(rsObj, who); if (pd == null) continue;
                var pub = NGet(pd, "publicData");
                var talents = (NGet(pub!, "talents") as System.Collections.IList) ?? (NGet(pd, "talents") as System.Collections.IList);
                bool has197 = talents != null && talents.Cast<object>().Any(t => Convert.ToInt32(t) == 197);
                var lrd = NGet(pub!, "lastRoundData");
                var uc = (lrd != null ? NGet(lrd, "usedCards") : null) as System.Collections.IList;
                int cnt = 0; if (uc != null) foreach (var c in uc) { int b = Convert.ToInt32(getBase!.Invoke(null, new object[] { Convert.ToInt32(c) })); if (hexCards.Contains(b)) cnt++; }
                object? real = yi?.Invoke(null, new[] { pd });
                Console.WriteLine($"  [197-diag {who}] real YiGuaZiJieCheck={real}  | manual: has197={has197} hexCount={cnt} (expect true iff has197 && cnt==2)");
            }
        }
        catch (Exception e) { Console.WriteLine($"  [197-diag] err: {(e.InnerException ?? e).Message}"); }
        // Record's own stored per-turn log, if present (ground-truth trajectory to diff against).
        var recLog = NGet(rsObj, "log") as System.Collections.IList;
        if (recLog != null && recLog.Count > 0)
        {
            Console.WriteLine($"--- record.log ({recLog.Count} entries) ---");
            int i = 0; foreach (var e in recLog) { Console.WriteLine($"  [{i++}] {e}"); if (i >= 60) { Console.WriteLine("  ..."); break; } }
        }
        else Console.WriteLine("--- record.log: empty/absent ---");
    }

    // ── Trace ONE round of a JSON shared-battle record (build proto from {code,data}, per-turn trace) ──
    static void RunTraceJson(Assembly game, string file, string configsDir, int round)
    {
        var rbiType = game.GetType("Proto.RecentBattleInfo")!;
        var cfgMgr = game.GetType("ConfigManager")!;
        var bmType = game.GetType("BattleManager")!;
        var bm = New(bmType); SetStatic(bmType, "Instance", bm);
        NSet(bm, "currentGameStatus", New(game.GetType("Proto.GameStatus")!));
        NSet(bm, "currentScene", Enum.Parse(game.GetType("SceneType")!, "斗法阶段"));
        NSet(bm, "replaying", true);
        var freshCards = LoadConfigList(game, "CardConfig", configsDir);
        SetStatic(cfgMgr, "s_CardConfigs", freshCards); BuildDict(cfgMgr, "cardConfigDict", freshCards, "id");

        var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(file));
        if (!doc.RootElement.TryGetProperty("data", out var dataEl)) { Console.WriteLine("no data"); return; }
        var rbi = JsonToProto(game, rbiType, dataEl)!;
        if (NGet(rbi, "roundStats") is not System.Collections.IList rounds) { Console.WriteLine("no roundStats"); return; }
        object? rsObj = null; foreach (var rs in rounds) if (Convert.ToInt32(NGet(rs!, "round") ?? -1) == round) { rsObj = rs; break; }
        if (rsObj == null) { Console.WriteLine($"round {round} not found"); return; }
        int rec = Convert.ToInt32(NGet(rsObj, "hpDelta") ?? 0), recTurns = Convert.ToInt32(NGet(rsObj, "huiHeCount") ?? 0);
        foreach (var who in new[] { "p1", "p2" })
        {
            var pd = NGet(rsObj, who); if (pd == null) continue;
            var pub = NGet(pd, "publicData");
            Console.WriteLine($"--- deck {who} (char {NGet(pub!, "characterId")}, talents {string.Join(",", ((NGet(pub!, "talents") as System.Collections.IList)?.Cast<object>() ?? Enumerable.Empty<object>()))}) ---");
            try { var ui = BuildCharacterUI(game, pd); if (NGet(ui, "battleCardItems") is System.Collections.IList items) foreach (var ci in items) { var cfg = NGet(ci!, "cardConfig"); if (cfg != null) Console.WriteLine($"   grid{NGet(ci, "gridNumber")} id={NGet(cfg, "id")} atk={NGet(cfg, "attack")} def={NGet(cfg, "def")} lvl={NGet(cfg, "level")}"); } }
            catch (Exception e) { Console.WriteLine($"   deck err: {e.Message}"); }
        }
        Environment.SetEnvironmentVariable("ORACLE_TRACE_ROUND", round.ToString());
        var (lhp, rhp, turns) = RunOneRound(game, rsObj, round, out var fault, out _);
        Environment.SetEnvironmentVariable("ORACLE_TRACE_ROUND", null);
        Console.WriteLine($"=== native: {lhp}/{rhp} delta={lhp - rhp} turns={turns}  (rec {rec}/{recTurns})  {(fault != null ? "FAULT: " + fault : "")} ===");
    }

    // ── Run shared-battle JSON records (the {code,data} export format) through the oracle ──────────
    // Each file's `data` is a RecentBattleInfo in JSON; build the proto by reflection and sweep its rounds.
    static void RunJsonRecords(Assembly game, string dir, string configsDir, int limit)
    {
        var rbiType = game.GetType("Proto.RecentBattleInfo")!;
        var cfgMgr = game.GetType("ConfigManager")!;
        var bmType = game.GetType("BattleManager")!;
        var bm = New(bmType); SetStatic(bmType, "Instance", bm);
        NSet(bm, "currentGameStatus", New(game.GetType("Proto.GameStatus")!));
        NSet(bm, "currentScene", Enum.Parse(game.GetType("SceneType")!, "斗法阶段"));
        NSet(bm, "replaying", true);

        bool failCards = Environment.GetEnvironmentVariable("ORACLE_FAIL_CARDS") == "1";
        var files = Directory.GetFiles(dir, "*_p*.json", SearchOption.AllDirectories).OrderBy(x => x).ToList();
        int total = 0, pass = 0, parseFail = 0, fileN = 0;
        var seen = new System.Collections.Generic.HashSet<string>();   // dedup battles seen from multiple perspectives
        var smPass = new System.Collections.Generic.Dictionary<int, int>(); var smTot = new System.Collections.Generic.Dictionary<int, int>();
        var gmPass = new System.Collections.Generic.Dictionary<int, int>(); var gmTot = new System.Collections.Generic.Dictionary<int, int>();
        foreach (var file in files)
        {
            if (limit > 0 && fileN >= limit) break;
            fileN++;
            System.Text.Json.JsonDocument doc;
            try { doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(file)); }
            catch { parseFail++; continue; }
            if (!doc.RootElement.TryGetProperty("data", out var dataEl) || dataEl.ValueKind != System.Text.Json.JsonValueKind.Object) continue;
            int sm = dataEl.TryGetProperty("seasonMec", out var smE) && smE.TryGetInt32(out var smv) ? smv : -1;
            int gm = dataEl.TryGetProperty("gameMode", out var gmE) && gmE.TryGetInt32(out var gmv) ? gmv : -1;
            object rbi; try { rbi = JsonToProto(game, rbiType, dataEl)!; } catch { parseFail++; continue; }
            if (NGet(rbi, "roundStats") is not System.Collections.IList rounds) continue;
            var gid = dataEl.TryGetProperty("gameId", out var g) ? g.ToString() : file;
            foreach (var rs in rounds)
            {
                if (NGet(rs!, "p1") == null || NGet(rs!, "p2") == null) continue;   // combat rounds only
                int round = Convert.ToInt32(NGet(rs!, "round") ?? 0);
                if (!seen.Add($"{gid}-{round}")) continue;                          // dedup across perspectives
                // pristine CardConfig templates PER ROUND: special-card evolution mutates the shared
                // CardConfig objects in place; each recorded combat round is independent, so reset to
                // avoid an earlier round's evolution leaking into a later round (within-file leakage).
                var freshCards = LoadConfigList(game, "CardConfig", configsDir);
                SetStatic(cfgMgr, "s_CardConfigs", freshCards);
                BuildDict(cfgMgr, "cardConfigDict", freshCards, "id");
                int rec = Convert.ToInt32(NGet(rs!, "hpDelta") ?? 0), recTurns = Convert.ToInt32(NGet(rs!, "huiHeCount") ?? 0);
                bool p = false; int simDelta = 0, simTurns = 0; string? fault = null;
                try { var (lhp, rhp, turns) = RunOneRound(game, rs!, round, out fault, out _); simDelta = lhp - rhp; simTurns = turns; p = simDelta == rec && turns == recTurns; }
                catch (Exception ex) { fault = (ex.InnerException ?? ex).Message.Split('\n')[0]; }
                // ORACLE_FAIL_CARDS=1: emit EVERY round's pass-flag + error + the cards both sides used, so
                // the cards/mechanics the oracle mishandles can be found by per-card FAIL-RATE correlation.
                if (failCards)
                {
                    var cards = new System.Collections.Generic.List<int>();
                    foreach (var who in new[] { "p1", "p2" })
                    {
                        var pub = NGet(NGet(rs!, who) ?? new object(), "publicData"); var lrd = pub != null ? NGet(pub, "lastRoundData") : null;
                        if (lrd != null && NGet(lrd, "usedCards") is System.Collections.IList uc) foreach (var c in uc) cards.Add(Convert.ToInt32(c));
                    }
                    var p1pub = NGet(NGet(rs!, "p1") ?? new object(), "publicData");
                    var tal = p1pub != null && NGet(p1pub, "talents") is System.Collections.IList tl ? string.Join(",", tl.Cast<object>()) : "";
                    Console.WriteLine($"R {(p ? 1 : 0)} sm={sm} char={Convert.ToInt32(NGet(p1pub ?? new object(), "characterId") ?? 0)} hperr={simDelta - rec} fault={(fault ?? "none").Split(':')[0]} game={gid} rnd={round} src={Path.GetFileName(file)} talents={tal} cards={string.Join(",", cards.Distinct())}");
                }
                total++; smTot[sm] = smTot.GetValueOrDefault(sm) + 1; gmTot[gm] = gmTot.GetValueOrDefault(gm) + 1;
                if (p) { pass++; smPass[sm] = smPass.GetValueOrDefault(sm) + 1; gmPass[gm] = gmPass.GetValueOrDefault(gm) + 1; }
            }
        }
        Console.WriteLine($"=== JSON RECORDS: {pass}/{total} combat rounds exact ({(total > 0 ? 100.0 * pass / total : 0):F1}%) | {fileN} files, {seen.Count} unique battles, {parseFail} parse-fail ===");
        Console.WriteLine("  by seasonMec:");
        foreach (var kv in smTot.OrderByDescending(k => k.Value))
            Console.WriteLine($"    seasonMec {kv.Key,2}: {smPass.GetValueOrDefault(kv.Key)}/{kv.Value} ({100.0 * smPass.GetValueOrDefault(kv.Key) / kv.Value:F1}%)");
        Console.WriteLine("  by gameMode:");
        foreach (var kv in gmTot.OrderByDescending(k => k.Value))
            Console.WriteLine($"    gameMode {kv.Key,2}: {gmPass.GetValueOrDefault(kv.Key)}/{kv.Value} ({100.0 * gmPass.GetValueOrDefault(kv.Key) / kv.Value:F1}%)");
    }

    // Generic reflection JSON->proto builder: set each matching field (scalar/enum/message/List/Dictionary).
    static object? JsonToProto(Assembly game, Type t, System.Text.Json.JsonElement el)
    {
        var obj = New(t);
        foreach (var prop in el.EnumerateObject())
        {
            var f = FindField(t, prop.Name) ?? FindField(t, $"<{prop.Name}>k__BackingField");
            var pi = t.GetProperty(prop.Name, ANY);
            Type? ft = f?.FieldType ?? pi?.PropertyType;
            if (ft == null) continue;
            object? val;
            try { val = BuildJsonValue(game, ft, prop.Value); } catch { continue; }
            if (val == null && prop.Value.ValueKind != System.Text.Json.JsonValueKind.Null) continue;
            try { if (f != null) f.SetValue(obj, val); else pi!.GetSetMethod(true)?.Invoke(obj, new[] { val }); } catch { }
        }
        return obj;
    }
    static object? BuildJsonValue(Assembly game, Type ft, System.Text.Json.JsonElement el)
    {
        var JK = System.Text.Json.JsonValueKind.Object; var JA = System.Text.Json.JsonValueKind.Array;
        if (el.ValueKind == System.Text.Json.JsonValueKind.Null) return null;
        if (ft.IsGenericType && ft.GetGenericTypeDefinition() == typeof(System.Collections.Generic.List<>) && el.ValueKind == JA)
        {
            var et = ft.GetGenericArguments()[0];
            var list = (System.Collections.IList)New(ft);
            foreach (var e in el.EnumerateArray()) list.Add(BuildJsonValue(game, et, e));
            return list;
        }
        if (ft.IsGenericType && ft.GetGenericTypeDefinition() == typeof(System.Collections.Generic.Dictionary<,>) && el.ValueKind == JK)
        {
            var kt = ft.GetGenericArguments()[0]; var vt = ft.GetGenericArguments()[1];
            var dict = (System.Collections.IDictionary)New(ft);
            foreach (var p in el.EnumerateObject()) { var k = ConvScalar(kt, p.Name); if (k != null) dict[k] = BuildJsonValue(game, vt, p.Value); }
            return dict;
        }
        if (el.ValueKind == JK && ft.IsClass && ft != typeof(string)) return JsonToProto(game, ft, el);
        return ConvJsonScalar(ft, el);
    }
    static object? ConvJsonScalar(Type ft, System.Text.Json.JsonElement el)
    {
        var u = Nullable.GetUnderlyingType(ft) ?? ft;
        try
        {
            if (u.IsEnum) return Enum.ToObject(u, el.GetInt64());
            if (u == typeof(string)) return el.ValueKind == System.Text.Json.JsonValueKind.String ? el.GetString() : el.ToString();
            if (u == typeof(int)) return el.TryGetInt32(out var i) ? i : (int)el.GetInt64();
            if (u == typeof(long)) return el.GetInt64();
            if (u == typeof(bool)) return el.ValueKind == System.Text.Json.JsonValueKind.True;
            if (u == typeof(float)) return (float)el.GetDouble();
            if (u == typeof(double)) return el.GetDouble();
            if (u == typeof(uint)) return el.GetUInt32();
            if (u == typeof(ulong)) return el.GetUInt64();
        }
        catch { return null; }
        return null;
    }
    static object? ConvScalar(Type kt, string s)
    {
        var u = Nullable.GetUnderlyingType(kt) ?? kt;
        if (u == typeof(int)) return int.TryParse(s, out var i) ? i : 0;
        if (u == typeof(long)) return long.TryParse(s, out var l) ? l : 0L;
        if (u.IsEnum) return int.TryParse(s, out var e) ? Enum.ToObject(u, e) : null;
        return s;
    }

    // ── Reconstruction-fidelity audit: build every fighter, flag usedCards that drop from the deck ──
    // (null/unresolved cardConfig). A dropped card → a short deck → silent combat divergence. Prints a
    // JSON line per anomalous fighter + a summary, so drops can be correlated against the parity sweep.
    static void RunReconAudit(Assembly game, string recordsDir)
    {
        var rbiType = game.GetType("Proto.RecentBattleInfo")!;
        var bmType = game.GetType("BattleManager")!;
        var bm = New(bmType); SetStatic(bmType, "Instance", bm);
        NSet(bm, "currentGameStatus", New(game.GetType("Proto.GameStatus")!));
        NSet(bm, "currentScene", Enum.Parse(game.GetType("SceneType")!, "斗法阶段"));
        NSet(bm, "replaying", true);
        // Capture exceptions SWALLOWED during BuildCharacterUI (special-card evolution etc.) — these never
        // reach RunOneRound's fault hook (it's installed after the build), so they're silent divergences.
        string? buildFault = null;
        EventHandler<System.Runtime.ExceptionServices.FirstChanceExceptionEventArgs> fce = (s, e) =>
        {
            if (buildFault != null) return;
            var frame = new System.Diagnostics.StackTrace(e.Exception, false).GetFrames()?
                .FirstOrDefault(f => { var ns = f.GetMethod()?.DeclaringType?.Namespace; return string.IsNullOrEmpty(ns) || (!ns!.StartsWith("System") && !ns.StartsWith("Cysharp")); });
            var fm = frame?.GetMethod();
            buildFault = $"{e.Exception.GetType().Name} @ {fm?.DeclaringType?.Name}.{fm?.Name}+IL_{frame?.GetILOffset():X4}";
        };
        AppDomain.CurrentDomain.FirstChanceException += fce;
        int fighters = 0, withNull = 0, totalNull = 0, buildFail = 0, withSwallow = 0;
        var faultHist = new System.Collections.Generic.Dictionary<string, int>();
        foreach (var bin in Directory.GetFiles(recordsDir, "*.bin").OrderBy(x => x))
        {
            var stem = Path.GetFileNameWithoutExtension(bin);
            object rbi = New(rbiType);
            try { ((wProtobuf.IMessage)rbi).MergeFrom(new wProtobuf.MessageStream(File.ReadAllBytes(bin))); }
            catch { continue; }
            if (NGet(rbi, "roundStats") is not System.Collections.IList rounds) continue;
            foreach (var rs in rounds)
            {
                int round = Convert.ToInt32(NGet(rs!, "round") ?? -1);
                foreach (var who in new[] { "p1", "p2" })
                {
                    var pd = NGet(rs!, who); if (pd == null) continue;
                    fighters++;
                    buildFault = null;
                    try
                    {
                        var ui = BuildCharacterUI(game, pd);
                        var items = NGet(ui, "battleCardItems") as System.Collections.IList;
                        int total = items?.Count ?? 0, nulls = 0;
                        if (items != null) foreach (var ci in items) if (NGet(ci!, "cardConfig") == null) nulls++;
                        if (nulls > 0) { withNull++; totalNull += nulls; }
                        if (buildFault != null)
                        {
                            withSwallow++;
                            faultHist[buildFault] = faultHist.GetValueOrDefault(buildFault) + 1;
                            Console.WriteLine($"{{\"rec\":\"{stem}\",\"round\":{round},\"who\":\"{who}\",\"deck\":{total},\"nullCfg\":{nulls},\"swallowed\":\"{buildFault}\"}}");
                        }
                    }
                    catch { buildFail++; }
                }
            }
        }
        AppDomain.CurrentDomain.FirstChanceException -= fce;
        Console.WriteLine($"=== RECON AUDIT: {fighters} fighters | {withNull} null-config drops | {withSwallow} with a SWALLOWED build-time exception | {buildFail} build-fail ===");
        foreach (var kv in faultHist.OrderByDescending(k => k.Value).Take(20))
            Console.WriteLine($"   {kv.Value,5}  {kv.Key}");
    }

    // ── Fixture run: load a fixture JSON, build both characters, RunOneRound, emit JSON line ───────
    // Matches the ILRuntime RunFixture JSON schema (same fields, "engine":"oracle").
    static void RunNativeFixture(Assembly game, string fixturePath)
        => RunFixtureFromText(game, File.ReadAllText(fixturePath));

    // Run one fixture given its JSON TEXT (a file's contents, or a single --serve stdin line). Emits exactly
    // one result JSON line on stdout. Shared by --run-fixture (cold, one shot) and --serve (warm loop).
    static void RunFixtureFromText(Assembly game, string json)
    {
        var opts = new System.Text.Json.JsonSerializerOptions { PropertyNameCaseInsensitive = true };
        var fx = System.Text.Json.JsonSerializer.Deserialize<NativeFixture>(json, opts)!;

        // SOURCE-OF-TRUTH PATH: route to RunFixtureFromStat when the fixture carries `stat` (the native proto
        // shape in JSON, editable in the web UX), OR is a stat-cache `prime`, OR references a cached stat by id
        // (board-search / what-if {id, deck-edits}). Otherwise fall through to the legacy reconstruct paths.
        if (fx.stat != null || fx.prime == true || (!string.IsNullOrEmpty(fx.id) && s_StatCache.ContainsKey(fx.id)))
        {
            RunFixtureFromStat(game, fx);
            return;
        }
        // BIT-EXACT FALLBACK: legacy fixtures may carry only the raw round-stat proto bytes (statB64) — opaque
        // but bit-exact. (Pre-`stat` fixtures; re-run --enrich-fixtures to add the editable `stat`.)
        if (!string.IsNullOrEmpty(fx.statB64))
        {
            RunFixtureFromBlob(game, fx);
            return;
        }

        // Build the round-stat container RunOneRound consumes. Derive its type (and EVERY nested proto type
        // below) BY REFLECTION from the record schema — RecentBattleInfo.roundStats' ELEMENT type — so we
        // never hardcode a proto name a game update can rename/move (this path broke once on a stale
        // "Proto.BattlePublicData" guess). RunOneRound reads: br.p1, br.p2, br.mainViewId, br.battleParams.
        var rbiType = game.GetType("Proto.RecentBattleInfo")!;
        var brType = ElemType(MemberType(rbiType, "roundStats"))
                     ?? throw new Exception("could not derive round-stat type from RecentBattleInfo.roundStats");
        var pdType = MemberType(brType, "p1") ?? throw new Exception("round-stat type has no p1 member");
        var br = New(brType);

        // Populate main fields.
        NSet(br, "mainViewId", fx.mainViewId);
        var bpList = NGet(br, "battleParams");
        if (bpList is System.Collections.IList bpl) { foreach (var v in fx.battleParams) bpl.Add(v); }

        // Build p1 / p2 proto player data from fixture.
        var p1data = BuildPlayerDataFromFixture(game, pdType, fx.p1, fx.p1.uid);
        var p2data = BuildPlayerDataFromFixture(game, pdType, fx.p2, fx.p2.uid);
        NSet(br, "p1", p1data);
        NSet(br, "p2", p2data);

        // BattleManager replay singleton — Execute reads BattleManager.Instance.currentGameStatus (and
        // currentScene/replaying). The sweep & trace paths set this up; the fixture path must too, else
        // Execute NREs at the first get_currentGameStatus.
        var bmType = game.GetType("BattleManager")!;
        var bm = New(bmType);
        SetStatic(bmType, "Instance", bm);
        NSet(bm, "currentGameStatus", New(game.GetType("Proto.GameStatus")!));
        NSet(bm, "currentScene", Enum.Parse(game.GetType("SceneType")!, "斗法阶段"));
        NSet(bm, "replaying", true);

        // Collect per-turn trace for the log. s_OracleTrace fires for BattleCharacter mutators;
        // the turn index is read from s_OracleHuiHe (mirrored from huiHeCount by PatchExposeHuiHe).
        var beType = game.GetType("BattleExecuter")!;
        var traceLog = new List<object>();
        Action<object, string, int, int> hook = (recv, tag, a0, a1) =>
        {
            int t = Convert.ToInt32(GetStatic(beType, "s_OracleHuiHe") ?? 0);
            traceLog.Add(new { turn = t, tag, a0, a1 });
        };
        SetStatic(beType, "s_OracleTrace", hook);

        double roundMs; string? faultInfo;
        var (lhp, rhp, turns) = RunOneRound(game, br, fx.round, out faultInfo, out roundMs);
        SetStatic(beType, "s_OracleTrace", null);

        int recHp = fx.expected.GetValueOrDefault("hpDelta");
        int recTurns = fx.expected.GetValueOrDefault("huiHeCount");
        int recLife = fx.expected.GetValueOrDefault("lifeDamage");
        int simDelta = lhp - rhp;
        bool hpOk = simDelta == recHp, turnsOk = turns == recTurns;
        var outObj = new
        {
            engine = "oracle",
            ok = faultInfo == null,
            hpDelta = simDelta,
            leftHp = lhp,
            rightHp = rhp,
            turns,
            lifeDamage = s_LastLifeDamage,
            winner = simDelta > 0 ? "p1" : simDelta < 0 ? "p2" : "draw",
            expected = fx.expected,
            hpOk, turnsOk, lifeOk = s_LastLifeDamage == recLife,
            match = faultInfo == null && hpOk && turnsOk,
            log = traceLog,
            fault = faultInfo,
        };
        Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(outObj));
    }

    // SOURCE-OF-TRUTH fixture run: deserialize the round-stat from the editable native proto JSON (`stat`,
    // ProtoJson) — 1:1 with the proto, so it runs identically to the .bin while staying fully editable in the
    // web UX. Emits the per-turn trace log (what the UI's run-oracle shows).
    // Stat-cache: a --serve worker keeps stat JSON NODES by id (populated by `prime`). FromNode runs FRESH
    // off the cached node every time, so a cached run is bit-exact to a normal run — only the transport differs.
    static readonly System.Collections.Generic.Dictionary<string, string> s_StatCache = new();
    // Cached-br fast path: the DESERIALIZED round-stat kept by id, so a cached run skips FromNode entirely
    // (just swap usedCards + run). Valid only if combat doesn't mutate br across a run — guarded by a bleed
    // test; the string cache above is the fallback. Disable with ORACLE_NO_BRCACHE=1.
    static readonly System.Collections.Generic.Dictionary<string, object> s_BrCache = new();

    // Original firstPlayerId per primed id, so a go-first override on the SHARED cached br can be
    // restored for the next (non-override) request. Captured at prime time.
    static readonly System.Collections.Generic.Dictionary<string, string?> s_OrigFirst = new();

    // A side's uid (the value firstPlayerId is compared against): br.{side}.publicData.uid.
    static string? SideUid(object br, string side)
    {
        var p = NGet(br, side); if (p == null) return null;
        var pub = NGet(p, "publicData"); if (pub == null) return null;
        return Convert.ToString(NGet(pub, "uid"));
    }

    // Set who takes the first turn. firstSide set -> firstPlayerId = that side's uid (force go-first);
    // else restore the recorded value for `id` (the shared cached br may carry a prior override).
    static void ApplyFirst(object br, string? firstSide, string? id)
    {
        if (!string.IsNullOrEmpty(firstSide))
        {
            var uid = SideUid(br, firstSide);
            if (uid != null) NSet(br, "firstPlayerId", uid);
        }
        else if (!string.IsNullOrEmpty(id) && s_OrigFirst.TryGetValue(id, out var orig) && orig != null)
            NSet(br, "firstPlayerId", orig);
    }

    // Override a side's usedCards (the board) on a round-stat, in place.
    static void OverrideDeck(object br, string side, List<int>? cards)
    {
        if (cards == null) return;
        var p = NGet(br, side); if (p == null) return;
        var pub = NGet(p, "publicData"); var lrd = pub != null ? NGet(pub, "lastRoundData") : null;
        if (lrd != null && NGet(lrd, "usedCards") is System.Collections.IList uc)
        { uc.Clear(); foreach (var id in cards) uc.Add(id); }
    }

    // Configs dir (set in RunServe) so the per-board reset in the in-process batch can reload talent/buff.
    static string? s_ConfigsDir;
    // Move-2 pristine CardConfig template (id -> pristine clone), built lazily once from s_CardConfigs.
    static System.Collections.Generic.Dictionary<int, object>? s_PristineCards;
    static object CloneCfg(object c) => c.GetType().GetMethod("Clone")!.Invoke(c, null)!;
    static System.Collections.Generic.Dictionary<int, object> PristineCards(Type cfgMgr)
    {
        if (s_PristineCards == null)
        {
            s_PristineCards = new();
            if (GetStatic(cfgMgr, "s_CardConfigs") is System.Collections.IList cards0)
                foreach (var c in cards0) { try { s_PristineCards[Convert.ToInt32(NGet(c!, "id"))] = CloneCfg(c!); } catch { } }
        }
        return s_PristineCards;
    }

    // Both sides' usedCards on a round-stat (the cards this round can mutate via special-card evolution).
    static List<int> RoundDeckIds(object rsObj)
    {
        var ids = new List<int>();
        foreach (var who in new[] { "p1", "p2" })
        {
            var p = NGet(rsObj, who); if (p == null) continue;
            var pub = NGet(p, "publicData"); var lrd = pub != null ? NGet(pub, "lastRoundData") : null;
            if (lrd != null && NGet(lrd, "usedCards") is System.Collections.IList uc)
                foreach (var c in uc) { try { ids.Add(Convert.ToInt32(c)); } catch { } }
        }
        return ids;
    }

    // PER-ROUND CardConfig restore: rounds within ONE record run in the same process, and special-card
    // evolution (e.g. Dream 枯木逢春) mutates a CardConfig in place — so a later round inherits an earlier
    // round's mutation unless we restore. Targeted in-memory clone from the pristine template (no disk),
    // so it's nearly free. (Proven: ds28dah-r08 = 19 turns in isolation, 21 after earlier rounds.)
    static void RestoreDeckConfigs(Assembly game, Type cfgMgr, string? configsDir, object rsObj)
    {
        // Reload pristine CardConfigs before each round. Special-card evolution mutates CardConfig objects in
        // place (including non-deck variant ids it creates), and combat reads them from the s_CardConfigs LIST
        // — so a targeted deck-only restore isn't enough; a full reload is. The file is OS-cached after the
        // first read, so this is a proto-parse (~ms), not real disk I/O. resetTB not needed (talent/buff
        // CONFIGS aren't mutated by combat — only their per-run buff instances on the fresh br).
        if (configsDir == null) return;
        try { ResetConfigsForDeck(game, cfgMgr, configsDir, RoundDeckIds(rsObj), full: true, resetTB: false); }
        catch { }
    }

    // Reset the configs a battle with this deck can mutate: targeted CardConfig restore (clone from the
    // pristine template) + talent/buff full reload. Shared by RunServe (per request) and the in-process
    // batch (per board) so neither bleeds across runs. `full` => reload all CardConfigs (escape hatch).
    static void ResetConfigsForDeck(Assembly game, Type cfgMgr, string configsDir,
                                    System.Collections.Generic.IEnumerable<int> deckIds, bool full, bool resetTB = true)
    {
        var cardDict = full ? null : GetStatic(cfgMgr, "cardConfigDict");
        var setItem = cardDict?.GetType().GetMethod("set_Item");
        if (full || cardDict == null || setItem == null)
        {
            var freshCards = LoadConfigList(game, "CardConfig", configsDir);
            SetStatic(cfgMgr, "s_CardConfigs", freshCards);
            BuildDict(cfgMgr, "cardConfigDict", freshCards, "id");
        }
        else
        {
            var pristine = PristineCards(cfgMgr);
            foreach (var id in deckIds)
                if (pristine.TryGetValue(id, out var p)) setItem.Invoke(cardDict, new object[] { id, CloneCfg(p) });
        }
        if (resetTB)
        {
            SetStatic(cfgMgr, "talentConfigs", LoadConfigList(game, "TalentConfig", configsDir));
            SetStatic(cfgMgr, "buffConfigs", LoadConfigList(game, "BuffConfig", configsDir));
        }
    }

    static void RunFixtureFromStat(Assembly game, NativeFixture fx)
    {
        bool rt = Environment.GetEnvironmentVariable("ORACLE_RUN_TIMING") == "1";
        var swD = rt ? System.Diagnostics.Stopwatch.StartNew() : null;
        var rbiType = game.GetType("Proto.RecentBattleInfo")!;
        var brType = ElemType(MemberType(rbiType, "roundStats"))!;

        // prime: cache the stat NODE under id, ack, don't run. Accepts either `stat` (ProtoJson node) OR
        // `statB64` (raw round-stat proto bytes, e.g. extracted straight from a recentBattleDatas record) —
        // the b64 is deserialized then ToNode'd so the cached path is identical to a stat-node prime.
        if (fx.prime == true)
        {
            if (string.IsNullOrEmpty(fx.id))
            { Console.WriteLine("{\"engine\":\"oracle\",\"ok\":false,\"error\":\"prime needs id\"}"); return; }
            System.Text.Json.Nodes.JsonNode? statNode = fx.stat;
            if (statNode == null && !string.IsNullOrEmpty(fx.statB64))
            {
                var brTmp = New(brType);
                ((wProtobuf.IMessage)brTmp).MergeFrom(new wProtobuf.MessageStream(Convert.FromBase64String(fx.statB64)));
                statNode = ProtoJson.ToNode(brTmp);
            }
            if (statNode == null)
            { Console.WriteLine("{\"engine\":\"oracle\",\"ok\":false,\"error\":\"prime needs stat or statB64\"}"); return; }
            // Cache the stat as a STRING (re-parse fallback) AND the deserialized br (fast path).
            s_StatCache[fx.id] = statNode.ToJsonString();
            var brP = ProtoJson.FromNode(brType, statNode)!;
            s_BrCache[fx.id] = brP;
            s_OrigFirst[fx.id] = Convert.ToString(NGet(brP, "firstPlayerId"));   // for go-first restore
            Console.WriteLine($"{{\"engine\":\"oracle\",\"primed\":true,\"id\":{System.Text.Json.JsonSerializer.Serialize(fx.id)}}}");
            return;
        }

        // Resolve the round-stat to run:
        //   - stat provided        -> FromNode it.
        //   - cached br (fast path)-> reuse the deserialized br directly (NO FromNode) when read-only is safe.
        //   - cached string        -> re-parse fresh (fallback).
        bool noBr = Environment.GetEnvironmentVariable("ORACLE_NO_BRCACHE") == "1";
        object? br;
        if (fx.stat != null) br = ProtoJson.FromNode(brType, fx.stat)!;
        else if (!noBr && !string.IsNullOrEmpty(fx.id) && s_BrCache.TryGetValue(fx.id, out var cbr)) br = cbr;
        else if (!string.IsNullOrEmpty(fx.id) && s_StatCache.TryGetValue(fx.id, out var cs))
            br = ProtoJson.FromNode(brType, System.Text.Json.Nodes.JsonNode.Parse(cs))!;
        else { Console.WriteLine("{\"engine\":\"oracle\",\"ok\":false,\"error\":\"no stat and no cached base for id\"}"); return; }
        double tDeser = rt ? swD!.Elapsed.TotalMilliseconds : 0;

        // describe: read-only — report each side's characterId + original board (lastRoundData.usedCards) so a
        // client can pick which side is "me" and seed board-search permutations. No combat run.
        if (fx.describe == true)
        {
            List<int> IntList(object? o)
            {
                var r = new List<int>();
                if (o is System.Collections.IList l) foreach (var x in l) r.Add(Convert.ToInt32(x));
                return r;
            }
            Dictionary<string, int> IntDict(object? o)
            {
                var r = new Dictionary<string, int>();
                if (o is System.Collections.IDictionary d)
                    foreach (System.Collections.DictionaryEntry e in d)
                        r[Convert.ToString(e.Key)!] = Convert.ToInt32(e.Value);
                return r;
            }
            Dictionary<string, List<int>> TalentDatas(object? o)
            {
                var r = new Dictionary<string, List<int>>();
                if (o is System.Collections.IDictionary d)
                    foreach (System.Collections.DictionaryEntry e in d)
                        r[Convert.ToString(e.Key)!] = IntList(e.Value != null ? NGet(e.Value, "commonParams") : null);
                return r;
            }
            object? SideInfo(string side)
            {
                var p = NGet(br, side); if (p == null) return null;
                var pub = NGet(p, "publicData");
                var lrd = pub != null ? NGet(pub, "lastRoundData") : null;
                return new {
                    uid = Convert.ToString(NGet(pub!, "uid")) ?? "",
                    // handCards = cards held this round; the achievability signal for a go-first line
                    // (absorbing a card grants +1 cultivation, and higher cultivation takes the first turn).
                    handCards = IntList(lrd != null ? NGet(lrd, "handCards") : null).Count,
                    characterId = Convert.ToInt32(NGet(pub!, "characterId") ?? 0),
                    level = Convert.ToInt32(NGet(pub, "level") ?? 0),
                    sect = Convert.ToInt32(NGet(pub, "sect") ?? 0),
                    career = Convert.ToInt32(NGet(pub, "career") ?? 0),
                    life = Convert.ToInt32(NGet(pub, "life") ?? 0),
                    extraMaxHp = Convert.ToInt32((lrd != null ? NGet(lrd, "extraMaxHp") : null) ?? NGet(pub, "extraMaxHp") ?? 0),
                    unlockGrids = Convert.ToInt32((lrd != null ? NGet(lrd, "unlockGrids") : null) ?? 8),
                    talents = IntList(NGet(pub, "talents")),
                    fateStrategies = IntList(lrd != null ? NGet(lrd, "fateStrategies") : null),
                    usedCards = IntList(lrd != null ? NGet(lrd, "usedCards") : null),
                    // Per-battle buff/talent instance state — the recorded round carries it; passing it
                    // back into a from-scratch fixture closes most of the state gap (RNG remains).
                    usedKeYinCards = IntList(lrd != null ? NGet(lrd, "usedKeYinCards") : null),
                    permanentBuffTempDatas = IntDict(lrd != null ? NGet(lrd, "permanentBuffTempDatas") : null),
                    talentTempDatas = IntDict(lrd != null ? NGet(lrd, "talentTempDatas") : null),
                    resonanceTalentFlags = IntDict(NGet(pub, "resonanceTalentFlags")),
                    talentDatas = TalentDatas(lrd != null ? NGet(lrd, "talentDatas") : null),
                };
            }
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new {
                engine = "oracle", describe = true,
                firstPlayerId = Convert.ToString(NGet(br, "firstPlayerId")) ?? "",   // who took the first turn
                round = Convert.ToInt32(NGet(br, "round") ?? 0),
                hpDelta = Convert.ToInt32(NGet(br, "hpDelta") ?? 0),
                lifeDamage = Convert.ToInt32(NGet(br, "lifeDamage") ?? 0),
                huiHeCount = Convert.ToInt32(NGet(br, "huiHeCount") ?? 0),
                p1 = SideInfo("p1"), p2 = SideInfo("p2"),
            }));
            return;
        }

        // Go-first override (or restore recorded order on the shared cached br). Applies to BOTH the
        // boards-batch and the single run below — set once here before any RunOneRound.
        ApplyFirst(br, fx.firstSide, fx.id);

        OverrideDeck(br, "p1", fx.p1Cards);
        OverrideDeck(br, "p2", fx.p2Cards);

        var bmType = game.GetType("BattleManager")!;
        var bm = New(bmType);
        SetStatic(bmType, "Instance", bm);
        NSet(bm, "currentGameStatus", New(game.GetType("Proto.GameStatus")!));
        NSet(bm, "currentScene", Enum.Parse(game.GetType("SceneType")!, "斗法阶段"));
        NSet(bm, "replaying", true);

        // IN-PROCESS BATCH: evaluate every board on the cached (read-only) br in this ONE request — per
        // board reset only its configs, swap its deck, run, collect (hpDelta, turns). One IPC for N boards.
        if (fx.boards != null && fx.boards.Count > 0)
        {
            var side = string.IsNullOrEmpty(fx.side) ? "p1" : fx.side;
            var cfgMgr = game.GetType("ConfigManager")!;
            // Talent/buff CONFIGS are read-only across a run (combat mutates buff INSTANCES, not configs) —
            // validated bit-exact across all 213 v0000 decks. So the batch skips the per-board talent/buff
            // disk-reload by default (+34% boards/s). ORACLE_BATCH_RESETTB=1 forces it back (conservative).
            bool resetTB = Environment.GetEnvironmentVariable("ORACLE_BATCH_RESETTB") == "1";
            // Per-board CardConfig restore stays: it's nearly free (targeted, ~8 cards from the in-memory
            // pristine template) AND necessary — special-card evolution mutates a CardConfig and would
            // accumulate across boards without it (proven by Move 2's dvmin0e bleed).
            s_RunFixtureLog = null;                                   // never build logs in batch
            bool bt = Environment.GetEnvironmentVariable("ORACLE_RUN_TIMING") == "1";
            double sumWall = 0, sumExec = 0;
            var results = new List<int[]>(fx.boards.Count);
            foreach (var board in fx.boards)
            {
                if (s_ConfigsDir != null) ResetConfigsForDeck(game, cfgMgr, s_ConfigsDir, board, false, resetTB);
                OverrideDeck(br, side, board);
                var swB = bt ? System.Diagnostics.Stopwatch.StartNew() : null;
                var (blhp, brhp, bturns) = RunOneRound(game, br, fx.round, out _, out var bex);
                if (bt) { sumWall += swB!.Elapsed.TotalMilliseconds; sumExec += bex; }
                // [hpDelta(p1-p2), turns, lifeDamage(signed: + = p1 deals destiny / p2 loses life)]
                results.Add(new[] { blhp - brhp, bturns, s_LastLifeDamage });
            }
            if (bt && fx.boards.Count > 0)
                Console.Error.WriteLine($"[batch-timing] {fx.boards.Count} boards: setup={sumWall/fx.boards.Count - sumExec/fx.boards.Count:F2}ms execute={sumExec/fx.boards.Count:F2}ms (wall/board={sumWall/fx.boards.Count:F2}ms)");
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new { engine = "oracle", batch = true, results }));
            return;
        }

        bool wantLog = fx.wantLog ?? true;                           // UI default: build+return the log
        var traceLog = new List<object>();
        s_RunFixtureLog = wantLog ? traceLog : null;                 // bulk: skip the hook entirely
        // Restore this fixture's deck CardConfigs before running — the warm worker (--serve) runs many
        // fixtures in one process, and special-card evolution mutates a CardConfig in place, so a prior
        // run bleeds into this one without a reset (the boards-batch path above already does this).
        RestoreDeckConfigs(game, game.GetType("ConfigManager")!, s_ConfigsDir, br);
        var swO = rt ? System.Diagnostics.Stopwatch.StartNew() : null;
        var (lhp, rhp, turns) = RunOneRound(game, br, fx.round, out var fault, out var execMs);
        s_RunFixtureLog = null;
        if (rt) Console.Error.WriteLine($"[run-timing] deser={tDeser:F2}ms build={swO!.Elapsed.TotalMilliseconds - execMs:F2}ms execute={execMs:F2}ms (log {traceLog.Count} entries)");

        int recHp = fx.expected.GetValueOrDefault("hpDelta");
        int recTurns = fx.expected.GetValueOrDefault("huiHeCount");
        int simDelta = lhp - rhp;
        var outObj = new
        {
            engine = "oracle", ok = fault == null, hpDelta = simDelta, leftHp = lhp, rightHp = rhp, turns,
            lifeDamage = s_LastLifeDamage, winner = simDelta > 0 ? "p1" : simDelta < 0 ? "p2" : "draw", expected = fx.expected,
            hpOk = simDelta == recHp, turnsOk = turns == recTurns, lifeOk = s_LastLifeDamage == fx.expected.GetValueOrDefault("lifeDamage"),
            match = fault == null && simDelta == recHp && turns == recTurns, log = traceLog, fault,
        };
        Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(outObj));
    }

    // Bit-exact fixture run: deserialize the round-stat from the embedded proto blob and run it exactly as
    // the .bin sweep does (mainViewId/deck/buff state all preserved → identical to the recorded combat).
    static void RunFixtureFromBlob(Assembly game, NativeFixture fx)
    {
        var rbiType = game.GetType("Proto.RecentBattleInfo")!;
        var brType = ElemType(MemberType(rbiType, "roundStats"))!;
        var br = New(brType);
        ((wProtobuf.IMessage)br).MergeFrom(new wProtobuf.MessageStream(Convert.FromBase64String(fx.statB64!)));

        var bmType = game.GetType("BattleManager")!;
        var bm = New(bmType);
        SetStatic(bmType, "Instance", bm);
        NSet(bm, "currentGameStatus", New(game.GetType("Proto.GameStatus")!));
        NSet(bm, "currentScene", Enum.Parse(game.GetType("SceneType")!, "斗法阶段"));
        NSet(bm, "replaying", true);

        var (lhp, rhp, turns) = RunOneRound(game, br, fx.round, out var fault, out _);
        int recHp = fx.expected.GetValueOrDefault("hpDelta");
        int recTurns = fx.expected.GetValueOrDefault("huiHeCount");
        int simDelta = lhp - rhp;
        var outObj = new
        {
            engine = "oracle", ok = fault == null, hpDelta = simDelta, leftHp = lhp, rightHp = rhp, turns,
            lifeDamage = s_LastLifeDamage, winner = simDelta > 0 ? "p1" : simDelta < 0 ? "p2" : "draw", expected = fx.expected,
            hpOk = simDelta == recHp, turnsOk = turns == recTurns, lifeOk = s_LastLifeDamage == fx.expected.GetValueOrDefault("lifeDamage"),
            match = fault == null && simDelta == recHp && turns == recTurns, log = Array.Empty<object>(), fault,
        };
        Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(outObj));
    }

    // ── Warm worker: --serve. One-time DLL+config load already paid; loop fixtures from stdin → stdout ──
    // Protocol: one fixture JSON per input line → one result JSON per output line. A readiness marker
    // {"serve":"ready"} is printed once before the loop so a client can sync past the startup banner.
    // `quit` or EOF ends it. Combat mutates config objects in place, so configs are reset to pristine
    // before EACH fixture (same reason RunRecordsSweep reloads per record) — no cross-request state bleed.
    // Extract the card ids in play (both decks) from a fixture's stat JSON — the only CardConfigs combat
    // can mutate (special-card evolution / upgrades operate on the cards actually played).
    static System.Collections.Generic.HashSet<int> ExtractDeckIds(string line)
    {
        var ids = new System.Collections.Generic.HashSet<int>();
        try
        {
            using var doc = System.Text.Json.JsonDocument.Parse(line);
            if (!doc.RootElement.TryGetProperty("stat", out var stat)) return ids;
            foreach (var pk in new[] { "p1", "p2" })
                if (stat.TryGetProperty(pk, out var p) && p.TryGetProperty("publicData", out var pub)
                    && pub.TryGetProperty("lastRoundData", out var lrd)
                    && lrd.TryGetProperty("usedCards", out var a) && a.ValueKind == System.Text.Json.JsonValueKind.Array)
                    foreach (var v in a.EnumerateArray())
                        if (v.TryGetInt32(out var id) && id != 0) ids.Add(id);
        }
        catch { }
        return ids;
    }

    static void RunServe(Assembly game, string configsDir)
    {
        var cfgMgr = game.GetType("ConfigManager")!;
        bool timing = Environment.GetEnvironmentVariable("ORACLE_SERVE_TIMING") == "1";
        bool fullReset = Environment.GetEnvironmentVariable("ORACLE_FULL_RESET") == "1";  // escape hatch
        s_ConfigsDir = configsDir;                                    // for the in-process batch reset
        PristineCards(cfgMgr);                                        // build the template once up front

        Console.WriteLine("{\"serve\":\"ready\"}");
        Console.Out.Flush();
        string? line;
        while ((line = Console.In.ReadLine()) != null)
        {
            line = line.Trim();
            if (line.Length == 0) continue;
            if (line == "quit" || line == "\"quit\"") break;
            try
            {
                var swR = timing ? System.Diagnostics.Stopwatch.StartNew() : null;
                // Per-request reset of the configs this battle's deck can mutate (targeted CardConfig +
                // talent/buff). Batch requests carry no deck in the line, so they reset PER BOARD inside.
                bool isBatch = line.Contains("\"boards\"");
                if (!isBatch) ResetConfigsForDeck(game, cfgMgr, configsDir, ExtractDeckIds(line), fullReset);
                swR?.Stop();
                var swX = timing ? System.Diagnostics.Stopwatch.StartNew() : null;
                RunFixtureFromText(game, line);   // emits exactly one result line
                if (timing) Console.Error.WriteLine($"[serve-timing] reset={swR!.Elapsed.TotalMilliseconds:F2}ms run={swX!.Elapsed.TotalMilliseconds:F2}ms");
            }
            catch (Exception e)
            {
                var ix = e.InnerException ?? e;
                Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new {
                    engine = "oracle", ok = false,
                    error = $"{ix.GetType().Name}: {ix.Message.Split('\n')[0]}" }));
            }
            Console.Out.Flush();
        }
        Console.Error.WriteLine("[serve] stdin closed, exiting");
    }

    // Enrich existing native fixtures (data/fixtures/<record>-r<NN>.json) with `statB64` = base64 of the raw
    // round-stat proto bytes, read from the source .bin records. Makes --run-fixture bit-exact AND the
    // committed fixtures self-contained/portable (no .bin needed at run time). Re-run when fixtures change.
    static void EnrichFixtures(Assembly game, string recordsDir, string fixturesDir)
    {
        var rbiType = game.GetType("Proto.RecentBattleInfo")!;
        int wrote = 0, recs = 0, noFixture = 0;
        var jsonOpts = new System.Text.Json.JsonSerializerOptions { WriteIndented = true };
        foreach (var bin in Directory.GetFiles(recordsDir, "*.bin").OrderBy(x => x))
        {
            var stem = Path.GetFileNameWithoutExtension(bin);
            object rbi = New(rbiType);
            try { ((wProtobuf.IMessage)rbi).MergeFrom(new wProtobuf.MessageStream(File.ReadAllBytes(bin))); }
            catch (Exception e) { Console.WriteLine($"  skip {stem}: {e.Message}"); continue; }
            if (NGet(rbi, "roundStats") is not System.Collections.IList roundStats) continue;
            recs++;
            foreach (var rs in roundStats)
            {
                int round = Convert.ToInt32(NGet(rs!, "round") ?? -1);
                var fixPath = Path.Combine(fixturesDir, $"{stem}-r{round:00}.json");
                if (!File.Exists(fixPath)) { noFixture++; continue; }
                var ws = new wProtobuf.MessageStream(256);
                ((wProtobuf.IMessage)rs).WriteTo(ws);
                var b64 = Convert.ToBase64String(ws.ToByteArray());
                var node = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(fixPath))!.AsObject();
                node["statB64"] = b64;
                // `stat` = the editable native proto shape (source of truth the web UX edits + --run-fixture runs).
                node["stat"] = ProtoJson.ToNode(rs);
                File.WriteAllText(fixPath, node.ToJsonString(jsonOpts));
                wrote++;
            }
        }
        Console.WriteLine($"enriched {wrote} fixtures from {recs} records ({noFixture} round-stats had no matching fixture)");
    }

    // Build a player-data proto from a FixturePlayer. ALL nested types are derived BY REFLECTION from the
    // member types of `pdType` (the round-stat's p1 type), so this never hardcodes a proto name — resilient
    // to game updates. Mirrors the shape the record's proto-deserialized p1/p2 produce for the sweep.
    static object BuildPlayerDataFromFixture(Assembly game, Type pdType, NativeFixturePlayer fp, string uid)
    {
        var pd = New(pdType);
        var pubType = MemberType(pdType, "publicData") ?? throw new Exception("player data has no publicData member");
        var pub = New(pubType);
        NSet(pub, "uid", uid); NSet(pub, "username", fp.username);
        NSet(pub, "characterId", fp.characterId);
        NSet(pub, "level", fp.level); NSet(pub, "exp", fp.exp);
        NSet(pub, "sect", fp.sect); NSet(pub, "career", fp.career);
        NSet(pub, "life", fp.life); NSet(pub, "extraMaxHp", fp.extraMaxHp);
        // Talents list.
        if (NGet(pub, "talents") is System.Collections.IList tl) foreach (var t in fp.talents) tl.Add(t);
        // resonanceTalentFlags dict.
        if (NGet(pub, "resonanceTalentFlags") is System.Collections.IDictionary rfd)
            foreach (var kv in fp.resonanceTalentFlags) rfd[kv.Key] = kv.Value;

        // lastRoundData (type derived from the publicData member).
        var lrdType = MemberType(pubType, "lastRoundData") ?? throw new Exception("publicData has no lastRoundData member");
        var lrd = New(lrdType);
        NSet(lrd, "level", fp.level); NSet(lrd, "exp", fp.exp);
        NSet(lrd, "life", fp.life); NSet(lrd, "extraMaxHp", fp.extraMaxHp);
        NSet(lrd, "unlockGrids", fp.unlockGrids);
        if (NGet(lrd, "usedCards") is System.Collections.IList uc) foreach (var c in fp.usedCards) uc.Add(c);
        if (NGet(lrd, "usedKeYinCards") is System.Collections.IList ky) foreach (var c in fp.usedKeYinCards) ky.Add(c);
        if (NGet(lrd, "fateStrategies") is System.Collections.IList fs) foreach (var c in fp.fateStrategies) fs.Add(c);
        if (NGet(lrd, "permanentBuffTempDatas") is System.Collections.IDictionary pbd)
            foreach (var kv in fp.permanentBuffTempDatas) pbd[kv.Key] = kv.Value;
        if (NGet(lrd, "talentTempDatas") is System.Collections.IDictionary ttd)
            foreach (var kv in fp.talentTempDatas) ttd[kv.Key] = kv.Value;
        // talentDatas: <BattleTalentData> per talent id (value type derived from the map member).
        var btdType = ElemType(MemberType(lrdType, "talentDatas"));
        if (btdType != null && NGet(lrd, "talentDatas") is System.Collections.IDictionary tdDict)
            foreach (var kv in fp.talentDatas)
            {
                var btd = New(btdType);
                if (NGet(btd, "commonParams") is System.Collections.IList cp) foreach (var v in kv.Value) cp.Add(v);
                tdDict[kv.Key] = btd;
            }
        // talentResonanceData (type derived from the lastRoundData member).
        var trdType = MemberType(lrdType, "talentResonanceData");
        if (trdType != null)
        {
            var trd = NGet(lrd, "talentResonanceData") ?? New(trdType);
            NSet(trd, "hasRefresh", fp.resHasRefresh);
            NSet(trd, "refreshChance", fp.resRefreshChance);
            if (NGet(trd, "refreshedIds") is System.Collections.IList ri) { ri.Clear(); foreach (var v in fp.resRefreshedIds) ri.Add(v); }
            NSet(lrd, "talentResonanceData", trd);
        }
        // Also sync lrd.talents (combat reads it from lrd, not only pub).
        if (NGet(lrd, "talents") is System.Collections.IList lt2) foreach (var t in fp.talents) lt2.Add(t);

        NSet(pub, "lastRoundData", lrd);
        NSet(pd, "publicData", pub);
        // privateData: mirror usedCards / talentResonanceData so the engine's privateData path reads correctly.
        var privType = MemberType(pdType, "privateData");
        if (privType != null)
        {
            var priv = NGet(pd, "privateData") ?? New(privType);
            if (NGet(priv, "usedCards") is System.Collections.IList puc) foreach (var c in fp.usedCards) puc.Add(c);
            if (trdType != null && NGet(priv, "talentResonanceData") is object ptrd)
            {
                NSet(ptrd, "hasRefresh", fp.resHasRefresh);
                NSet(ptrd, "refreshChance", fp.resRefreshChance);
                if (NGet(ptrd, "refreshedIds") is System.Collections.IList ri2) { ri2.Clear(); foreach (var v in fp.resRefreshedIds) ri2.Add(v); }
            }
            if (NGet(priv, "talentDatas") is System.Collections.IDictionary ptdDict && btdType != null)
                foreach (var kv in fp.talentDatas)
                {
                    var btd = New(btdType);
                    if (NGet(btd, "commonParams") is System.Collections.IList cp) foreach (var v in kv.Value) cp.Add(v);
                    ptdDict[kv.Key] = btd;
                }
            NSet(pd, "privateData", priv);
        }
        return pd;
    }

    // JSON-deserialization types for native fixture (mirror Program.cs Fixture / FixturePlayer).
    sealed class NativeFixturePlayer
    {
        public string uid { get; set; } = "";
        public string username { get; set; } = "";
        public int characterId { get; set; }
        public int level { get; set; }
        public int exp { get; set; }
        public int sect { get; set; }
        public int career { get; set; }
        public int life { get; set; }
        public int extraMaxHp { get; set; }
        public int unlockGrids { get; set; } = 8;
        public List<int> usedCards { get; set; } = new();
        public List<int> talents { get; set; } = new();
        public List<int> usedKeYinCards { get; set; } = new();
        public List<int> fateStrategies { get; set; } = new();
        public Dictionary<int, int> permanentBuffTempDatas { get; set; } = new();
        public Dictionary<int, int> talentTempDatas { get; set; } = new();
        public Dictionary<int, int> resonanceTalentFlags { get; set; } = new();
        public Dictionary<int, List<int>> talentDatas { get; set; } = new();
        public bool resHasRefresh { get; set; }
        public int resRefreshChance { get; set; }
        public List<int> resRefreshedIds { get; set; } = new();
    }
    sealed class NativeFixture
    {
        public string id { get; set; } = "";
        public string name { get; set; } = "";
        public string record { get; set; } = "";
        public string season { get; set; } = "";
        public int round { get; set; }
        public string mainViewId { get; set; } = "";
        public List<int> battleParams { get; set; } = new();
        public Dictionary<string, int> expected { get; set; } = new();
        public NativeFixturePlayer p1 { get; set; } = new();
        public NativeFixturePlayer p2 { get; set; } = new();
        // base64 of the raw round-stat proto bytes; when present, --run-fixture deserializes it directly
        // (bit-exact, identical to the .bin sweep) instead of lossy field reconstruction. Added by --enrich-fixtures.
        public string? statB64 { get; set; }
        // `stat` = the round-stat as the NATIVE proto shape in JSON (ProtoJson), 1:1 and EDITABLE. This is the
        // source of truth: the web UX edits this, and --run-fixture deserializes it straight to proto (no
        // flatten/rebuild, no opaque bytes). Preferred over statB64 (opaque) and the flat p1/p2 (lossy).
        public System.Text.Json.Nodes.JsonNode? stat { get; set; }
        // Transport: when false, the per-turn log is neither built nor returned (bulk/training has no
        // front-end). Default true so the UI always gets its presentation log. The log is cheap to build
        // (~0.08ms) but carries hundreds of entries back over the pipe, so omitting it shrinks the response.
        public bool? wantLog { get; set; }
        // Stat-cache (board-search / what-if transport): a --serve worker caches the stat JSON NODE under `id`.
        // `prime` = cache the node from `stat` and ack, don't run. A later request with `id` set and `stat`
        // null deserializes FRESH from the cached node (ProtoJson.FromNode each run — identical to the normal
        // path, so bit-exact) but the client sends only the deck edits below, not the 20KB stat, over the pipe.
        public bool? prime { get; set; }
        public bool? describe { get; set; }       // read-only: return each side's {characterId, usedCards} from the cached/given stat
        public List<int>? p1Cards { get; set; }   // override side p1's usedCards (the board being searched)
        public List<int>? p2Cards { get; set; }   // override side p2's usedCards (rarely needed)
        // In-process BATCH board-search: evaluate many boards on the cached br in ONE request (one IPC
        // round-trip instead of N). `side` = which side's usedCards each board overrides (default p1).
        public List<List<int>>? boards { get; set; }
        public string? side { get; set; }
        // Go-first override: force this side ("p1"/"p2") to take the first turn by setting the
        // round-stat's firstPlayerId to that side's uid. null/"" leaves the recorded turn order.
        // (BattleExecuter decides order by `leftCharacter.battleTempData.uid == battleResult.firstPlayerId`.)
        public string? firstSide { get; set; }
    }

    // ── Native reflection helpers (real CLR objects, no ILRuntime wrappers) ──────────────────────
    const BindingFlags ANY = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
    // When a caller (e.g. --run-fixture for the UI) wants the per-turn mutation log returned as data, it sets
    // this; RunOneRound appends a structured {turn,side,tag,a0,a1} per mutation (independent of the env tracer).
    static System.Collections.Generic.List<object>? s_RunFixtureLog;
    static System.Reflection.FieldInfo? FindField(Type? t, string name)
    {
        for (; t != null; t = t.BaseType)
        { var f = t.GetField(name, ANY | BindingFlags.DeclaredOnly); if (f != null) return f; }
        return null;
    }
    // Declared type of a member (property, field, or auto-prop backing field), walking base types. Used to
    // derive nested proto types by reflection instead of hardcoding "Proto.X" names (game-update resilient).
    static Type? MemberType(Type? t, string name)
    {
        for (var x = t; x != null; x = x.BaseType)
        {
            var p = x.GetProperty(name, ANY | BindingFlags.DeclaredOnly); if (p != null) return p.PropertyType;
            var f = x.GetField(name, ANY | BindingFlags.DeclaredOnly); if (f != null) return f.FieldType;
            var bf = x.GetField($"<{name}>k__BackingField", ANY | BindingFlags.DeclaredOnly); if (bf != null) return bf.FieldType;
        }
        return null;
    }
    // Element/value type of a collection: List<T>/RepeatedField<T> -> T, MapField<K,V>/Dictionary<K,V> -> V,
    // T[] -> T. Used with MemberType to derive repeated/map proto element types.
    static Type? ElemType(Type? t)
    {
        if (t == null) return null;
        if (t.IsArray) return t.GetElementType();
        if (t.IsGenericType) { var ga = t.GetGenericArguments(); return ga[ga.Length - 1]; }
        foreach (var c in t.GetInterfaces())
            if (c.IsGenericType && c.GetGenericTypeDefinition() == typeof(IEnumerable<>)) return c.GetGenericArguments()[0];
        return null;
    }
    static object? NGet(object o, string field)
    {
        foreach (var n in new[] { field, $"<{field}>k__BackingField" }) { var f = FindField(o.GetType(), n); if (f != null) return f.GetValue(o); }
        return o.GetType().GetProperty(field, ANY)?.GetValue(o);
    }
    static void NSet(object o, string field, object? val)
    {
        foreach (var n in new[] { field, $"<{field}>k__BackingField" }) { var f = FindField(o.GetType(), n); if (f != null) { f.SetValue(o, val); return; } }
        o.GetType().GetProperty(field, ANY)?.GetSetMethod(true)?.Invoke(o, new[] { val });
    }
    static object New(Type t)
    {
        try { return Activator.CreateInstance(t, nonPublic: true)!; }
        catch { return System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(t); }
    }
    static void ListAdd(object list, object item) => list.GetType().GetMethod("Add")!.Invoke(list, new[] { item });

    // Diagnostic: when a method binds wrong (MissingMethodException despite a matching DummyDll sig),
    // the usual cause is type-identity duplication — the same type name defined in >1 loaded assembly,
    // so the game's call-site token and the facade's parameter resolve to different CLR types. Dump
    // every loaded definition of the type + each overload's parameter assemblies to see the split.
    static void DiagnoseType(string typeName, string methodName)
    {
        // Which UnityEngine.CoreModule assemblies are loaded, and can each materialize LogType?
        foreach (var asm in AssemblyLoadContext.Default.Assemblies.Where(a => a.GetName().Name == "UnityEngine.CoreModule"))
        {
            Console.WriteLine($"  [DIAG] loaded UnityEngine.CoreModule @ {asm.Location}");
            try
            {
                var lt = asm.GetType("UnityEngine.LogType", throwOnError: false);
                Console.WriteLine($"         GetType(UnityEngine.LogType) = {(lt != null ? lt.FullName : "NULL")}");
            }
            catch (Exception e) { Console.WriteLine($"         GetType threw {e.GetType().Name}: {e.Message}"); }
            try { var n = asm.GetTypes().Length; Console.WriteLine($"         GetTypes() = {n} types"); }
            catch (ReflectionTypeLoadException rt)
            {
                Console.WriteLine($"         GetTypes() ReflectionTypeLoadException: {rt.Types.Count(t => t != null)} ok, {rt.LoaderExceptions.Length} errors");
                foreach (var le in rt.LoaderExceptions.Where(x => x != null).Take(3).DistinctBy(x => x!.Message)) Console.WriteLine($"           - {le!.Message}");
            }
            catch (Exception e) { Console.WriteLine($"         GetTypes() threw {e.GetType().Name}: {e.Message}"); }
        }
    }

    // Diagnostic: report whether an assembly is already loaded and where from, then try to materialize
    // all its types to surface the REAL load error (FileLoadException usually hides a TypeLoad in a dep).
    static void DiagnoseLoad(string asmName)
    {
        var loaded = AssemblyLoadContext.Default.Assemblies.Where(a => a.GetName().Name == asmName).ToList();
        Console.WriteLine($"  [DIAG] '{asmName}' loaded copies: {loaded.Count}");
        foreach (var a in loaded)
        {
            Console.WriteLine($"    @ {a.Location}");
            try { var n = a.GetTypes().Length; Console.WriteLine($"      GetTypes() = {n}"); }
            catch (ReflectionTypeLoadException rt)
            {
                Console.WriteLine($"      GetTypes() ReflectionTypeLoadException: {rt.LoaderExceptions.Length} errors");
                foreach (var le in rt.LoaderExceptions.Where(x => x != null).Take(5).DistinctBy(x => x!.Message)) Console.WriteLine($"        - {le!.GetType().Name}: {le!.Message}");
            }
            catch (Exception e) { Console.WriteLine($"      GetTypes() {e.GetType().Name}: {e.Message}"); }
        }
    }

    static void RunBattleProbe(System.Reflection.Assembly game, string recordPath)
    {
        Console.WriteLine($"  [M4] loading record {Path.GetFileName(recordPath)} natively...");
        // Deserialize the .bin (RecentBattleInfo) via the game's proto + wProtobuf — same as the
        // ILRuntime records-dir sweep, but native.
        var rbi = New(game.GetType("Proto.RecentBattleInfo")!);
        var ms = new wProtobuf.MessageStream(File.ReadAllBytes(recordPath));
        game.GetType("Proto.RecentBattleInfo")!.GetMethod("MergeFrom", ANY)!.Invoke(rbi, new object[] { ms });
        var roundStats = (System.Collections.IList)NGet(rbi, "roundStats")!;
        Console.WriteLine($"  [M4] record has {roundStats.Count} rounds");
        if (roundStats.Count == 0) return;

        // BattleManager singleton (replay mode) — set up once, reused per round.
        var bm = New(game.GetType("BattleManager")!);
        SetStatic(game.GetType("BattleManager")!, "Instance", bm);
        NSet(bm, "currentGameStatus", New(game.GetType("Proto.GameStatus")!));
        NSet(bm, "currentScene", Enum.Parse(game.GetType("SceneType")!, "斗法阶段"));
        NSet(bm, "replaying", true);

        // Run EVERY round through the real native combat and compare hpDelta+turns to the recording —
        // configs are loaded once, so each round costs only combat time. JIT-warm the first round, then
        // time the rest to report a clean ms/battle vs the ~92ms ILRuntime baseline.
        int hpPass = 0, turnPass = 0, bothPass = 0, faults = 0;
        double timedMs = 0; int timedN = 0;
        for (int r = 0; r < roundStats.Count; r++)
        {
            var br = roundStats[r]!;
            double roundMs; string? faultInfo;
            var (lhp, rhp, turns) = RunOneRound(game, br, r + 1, out faultInfo, out roundMs);
            if (r > 0) { timedMs += roundMs; timedN++; }   // skip round 0 (JIT warm-up) for the timing average
            int recHp = Convert.ToInt32(NGet(br, "hpDelta") ?? 0);
            int recTurns = Convert.ToInt32(NGet(br, "huiHeCount") ?? -1);
            bool hpOk = (lhp - rhp) == recHp, turnsOk = turns == recTurns;
            if (hpOk) hpPass++; if (turnsOk) turnPass++; if (hpOk && turnsOk) bothPass++; if (faultInfo != null) faults++;
            Console.WriteLine($"    r{r + 1,-2} hpΔ={lhp - rhp,4} (rec {recHp,4}) {(hpOk ? "OK  " : "MISS")}  turns={turns,2} (rec {recTurns,2}) {(turnsOk ? "OK  " : "MISS")}  {roundMs,6:F1}ms{(faultInfo != null ? "  FAULT: " + faultInfo : "")}");
        }
        Console.WriteLine($"  [M4] SUMMARY: hp {hpPass}/{roundStats.Count}, turns {turnPass}/{roundStats.Count}, both {bothPass}/{roundStats.Count}, faults {faults}");
        if (timedN > 0) Console.WriteLine($"  [M4] native combat: {timedMs / timedN:F1} ms/battle avg over {timedN} rounds (ILRuntime baseline ~92 ms)");
    }

    // Run one recorded round through the real native BattleExecuter.Execute and return (leftHp, rightHp,
    // turns). faulted=true if any exception was thrown inside Execute (a faulted card / unhandled visual
    // NRE) — surfaced so the caller can flag rounds that didn't run clean.
    static (int lhp, int rhp, int turns) RunOneRound(System.Reflection.Assembly game, object br, int roundNum, out string? faultInfo, out double ms)
    {
        var p1 = NGet(br, "p1")!; var p2 = NGet(br, "p2")!;
        var uiP1 = BuildCharacterUI(game, p1);
        var uiP2 = BuildCharacterUI(game, p2);

        var beHost = New(game.GetType("BattleExecuter")!);
        var mainViewId = NGet(br, "mainViewId");
        var p1Uid = NGet(NGet(p1, "publicData")!, "uid"); var p2Uid = NGet(NGet(p2, "publicData")!, "uid");
        bool p2IsLeft = Equals(p2Uid, mainViewId) && !Equals(p1Uid, mainViewId);
        var group = New(game.GetType("BattleCharacterUIGroup")!);
        NSet(group, "leftCharacterUI", p2IsLeft ? uiP2 : uiP1);
        NSet(group, "rightCharacterUI", p2IsLeft ? uiP1 : uiP2);
        NSet(beHost, "m_BattleCharacterUIGroup", group);
        NSet(beHost, "m_LeftCharacter", New(game.GetType("BattleCharacter")!));
        NSet(beHost, "m_RightCharacter", New(game.GetType("BattleCharacter")!));
        // Link each KeYinItem to its owning BattleCharacter (the __owner field injected by DllPatcher), so
        // KeYinItem.get_cardConfig reads the live battleTempData.battleKeYinCards[index] — the generic cardConfig
        // fix that replaced the bespoke swapKeYin/levelUpKeYin rewrites.
        void LinkOwners(object ui, object? character)
        {
            if (character != null && NGet(ui, "m_KeYinItems") is System.Collections.IList items)
                foreach (var it in items) if (it != null) try { NSet(it, "__owner", character); } catch { }
        }
        LinkOwners(p2IsLeft ? uiP2 : uiP1, NGet(beHost, "m_LeftCharacter"));
        LinkOwners(p2IsLeft ? uiP1 : uiP2, NGet(beHost, "m_RightCharacter"));
        // Execute's shell does `m_BattleOpeningVM.gameObject.SetActive(...)` unconditionally; that field
        // is scene-injected (null headless) -> NRE. Give it a non-null facade stub (its gameObject is
        // lazily non-null). m_BattleSceneBehaviour stays null — the game null-guards it (OnWin/OnLose).
        var vmField = FindField(beHost.GetType(), "m_BattleOpeningVM");
        if (vmField != null) NSet(beHost, "m_BattleOpeningVM", New(vmField.FieldType));
        var queue = NGet(beHost, "battleParamsQueue");
        if (queue != null && NGet(br, "battleParams") is System.Collections.IList bpl)
        { var enq = queue.GetType().GetMethod("Enqueue"); foreach (var bp in bpl) enq!.Invoke(queue, new object[] { Convert.ToInt32(bp) }); }

        // Reset the exposed turn counter (mirrors huiHeCount, persists across rounds in-process).
        SetStatic(game.GetType("BattleExecuter")!, "s_OracleHuiHe", 0);

        // Per-turn trace (env ORACLE_TRACE_ROUND=N): record every BattleCharacter stat mutation with its
        // side (L/R by receiver identity) + turn (s_OracleHuiHe) so a diverging round can be read off.
        var beType = game.GetType("BattleExecuter")!;
        var traceLog = new System.Collections.Generic.List<string>();
        bool tracing = Environment.GetEnvironmentVariable("ORACLE_TRACE_ROUND") == roundNum.ToString();
        if (tracing)
        {
            var leftChar = NGet(beHost, "m_LeftCharacter"); var rightChar = NGet(beHost, "m_RightCharacter");
            Action<object, string, int, int> hook = (recv, tag, a0, a1) =>
            {
                string side = ReferenceEquals(recv, leftChar) ? "L" : ReferenceEquals(recv, rightChar) ? "R" : "?";
                int t = Convert.ToInt32(GetStatic(beType, "s_OracleHuiHe") ?? -1);
                int hp = -1; try { var td = NGet(recv, "battleTempData"); if (td != null) hp = Convert.ToInt32(NGet(td, "hp")); } catch { }
                // For ModifyBuffValue/SetBuffValue a0=BuffType(enum int), a1=delta; for ModifyHp/Def/... a0=delta.
                bool isBuff = tag == "ModifyBuffValue" || tag == "SetBuffValue";
                string src = "";
                // ORACLE_DIAG_WOOD: capture the game-code method that activated a buff (e.g. JiHuoMuLing=238),
                // so we can see WHICH card/trigger fired it (legit deck card vs a spurious per-turn source).
                if (isBuff && a1 > 0 && Environment.GetEnvironmentVariable("ORACLE_DIAG_WOOD") == a0.ToString())
                {
                    bool pastMutator = false;
                    foreach (var f in new System.Diagnostics.StackTrace(true).GetFrames() ?? Array.Empty<System.Diagnostics.StackFrame>())
                    {
                        var m = f.GetMethod(); var dn = m?.DeclaringType?.Name ?? ""; var ns = m?.DeclaringType?.Namespace ?? "";
                        var mn = m?.Name ?? "";
                        if (mn is "ModifyBuffValue" or "SetBuffValue") { pastMutator = true; continue; }   // skip the hooked mutator itself
                        if (!pastMutator) continue;                                                          // skip the hook/Invoke frames before it
                        if (ns.StartsWith("System") || dn.StartsWith("<>") || dn == "NativeRunner") continue; // skip plumbing
                        src = $"  <= {dn}.{mn}"; break;                                                       // first real game caller
                    }
                }
                traceLog.Add(isBuff
                    ? $"t{t,2} {side} {tag,14} buff={a0,4} val={a1,4}  (hp={hp}){src}"
                    : $"t{t,2} {side} {tag,14} val={a0,4}            (hp={hp})");
            };
            SetStatic(beType, "s_OracleTrace", hook);
        }
        else if (s_RunFixtureLog is { } cap)
        {
            // Structured per-turn log for --run-fixture (UI) when the env tracer isn't active.
            var leftChar = NGet(beHost, "m_LeftCharacter"); var rightChar = NGet(beHost, "m_RightCharacter");
            SetStatic(beType, "s_OracleTrace", (Action<object, string, int, int>)((recv, tag, a0, a1) =>
            {
                string side = ReferenceEquals(recv, leftChar) ? "L" : ReferenceEquals(recv, rightChar) ? "R" : "?";
                int t = Convert.ToInt32(GetStatic(beType, "s_OracleHuiHe") ?? -1);
                cap.Add(new { turn = t, side, tag, a0, a1 });
            }));
        }
        else SetStatic(beType, "s_OracleTrace", null);

        // Capture the FIRST exception's type + message + first game-code frame (so faulting rounds name
        // exactly which method to nop/fix next).
        string? firstFault = null;
        var nreFilter = Environment.GetEnvironmentVariable("ORACLE_DIAG_NRE");   // e.g. "UpdateCardInfo"
        var nreSeen = new HashSet<string>();
        EventHandler<System.Runtime.ExceptionServices.FirstChanceExceptionEventArgs> fce = (s, e) =>
        {
            var st = new System.Diagnostics.StackTrace(e.Exception, false);
            // ORACLE_DIAG_NRE: dump the FULL top frames (incl. System) of any exception whose stack passes
            // through the named method, so we can see the exact throw site (e.g. the deepest deref).
            if (nreFilter != null && st.GetFrames() is { } frs && frs.Any(f => (f.GetMethod()?.DeclaringType?.Name + "." + f.GetMethod()?.Name).Contains(nreFilter)))
            {
                var sig = $"{e.Exception.GetType().Name}:{frs.FirstOrDefault()?.GetMethod()?.Name}";
                if (nreSeen.Add(sig))
                {
                    Console.WriteLine($"  [NRE {e.Exception.GetType().Name}: {e.Exception.Message.Split('\n')[0]}]");
                    foreach (var f in frs.Take(8)) { var m = f.GetMethod(); Console.WriteLine($"      at {m?.DeclaringType?.Name}.{m?.Name}+IL_{f.GetILOffset():X4}"); }
                }
            }
            if (firstFault != null) return;
            var frame = st.GetFrames()?.FirstOrDefault(f => { var m = f.GetMethod(); var ns = m?.DeclaringType?.Namespace; return string.IsNullOrEmpty(ns) || (!ns!.StartsWith("System") && !ns.StartsWith("Cysharp")); });
            var fm = frame?.GetMethod();
            firstFault = $"{e.Exception.GetType().Name} @ {fm?.DeclaringType?.Name}.{fm?.Name}+IL_{frame?.GetILOffset():X4}: {e.Exception.Message.Split('\n')[0]}";
        };
        AppDomain.CurrentDomain.FirstChanceException += fce;
        var sw = System.Diagnostics.Stopwatch.StartNew();
        try { game.GetType("BattleExecuter")!.GetMethod("Execute", ANY)!.Invoke(beHost, new object?[] { br, null, false }); }
        catch (Exception e) { firstFault ??= (e.InnerException ?? e).Message.Split('\n')[0]; }
        sw.Stop();
        AppDomain.CurrentDomain.FirstChanceException -= fce;
        if (tracing)
        {
            SetStatic(beType, "s_OracleTrace", null);
            Console.WriteLine($"  [TRACE round {roundNum}] {traceLog.Count} mutations:");
            foreach (var line in traceLog) Console.WriteLine($"      {line}");
        }

        // battleParams desync probe: a faithful replay consumes ALL of a round's recorded RNG outcomes,
        // so battleParamsQueue should be EMPTY at the end. Leftover => native skipped a roll
        // (GetNextRandomValue called too few times); underrun (-1 from GetNextParam) => native rolled too
        // many. Either is a desync that cascades the rest of the round's RNG.
        if (Environment.GetEnvironmentVariable("ORACLE_DIAG_PARAMS") == "1")
        {
            int inP = (NGet(br, "battleParams") as System.Collections.IList)?.Count ?? -1;
            int remP = queue != null ? Convert.ToInt32(queue.GetType().GetProperty("Count")?.GetValue(queue) ?? -1) : -1;
            Console.WriteLine($"  [battleParams] input={inP} remaining={remP} consumed={inP - remP}{(remP > 0 ? "  <== LEFTOVER (skipped rolls)" : "")}");
        }

        var lt = NGet(beHost, "m_LeftTempData"); var rt = NGet(beHost, "m_RightTempData");
        int lhp = lt != null ? Convert.ToInt32(NGet(lt, "hp")) : -999;
        int rhp = rt != null ? Convert.ToInt32(NGet(rt, "hp")) : -999;
        int turns = Convert.ToInt32(GetStatic(game.GetType("BattleExecuter")!, "s_OracleHuiHe") ?? -1);
        s_LastLifeDamage = CalcLifeDamage(lhp, rhp, roundNum);
        faultInfo = firstFault; ms = sw.Elapsed.TotalMilliseconds;
        return (lhp, rhp, turns);
    }

    // Life (命) damage dealt when a round ends in defeat — ports BattleExecuter.CalLifeDamage's standard
    // (non-TA21 / non-YuanGu / non-FastMode) branch. The game's call site (BattleCharacter.OnBattleLose) is
    // nopped headless, so we compute it from the final hp + round. Talent-115 / FateStrategy-21 tweaks are
    // rare and omitted. A turn-cap round with both sides alive deals 0. Read by the run outputs.
    static int s_LastLifeDamage;
    static int CalcLifeDamage(int lhp, int rhp, int round)
    {
        int loser = Math.Min(lhp, rhp), winner = Math.Max(lhp, rhp);
        if (loser > 0) return 0;                       // no defeat (turn cap, both alive)
        int num2 = winner - loser;
        int num;
        if (num2 <= 20) num = round + 1 + (int)Math.Ceiling(num2 / 5.0);
        else { int n3 = (int)Math.Ceiling((num2 - 20) / 10.0); if (n3 > 2 + round / 2) n3 = 2 + round / 2; num = round + 5 + n3; }
        if (round <= 9) num--;
        // Signed from the mainView (left) perspective, matching the recorded hpDelta convention: positive
        // when the LEFT player wins (right loses life), negative when the left player loses life.
        return (lhp >= rhp ? 1 : -1) * num;
    }

    // Native port of Program.BuildCharacterUI — build a BattleCharacterUI whose battleCardItems hold the
    // deck (each CardItem with cardInfo.id mutated + cardConfig cloned + RefreshSpecialCard run).
    static object BuildCharacterUI(System.Reflection.Assembly game, object playerData)
    {
        var uiType = game.GetType("BattleCharacterUI")!;
        var ciType = game.GetType("CardItem")!;
        var ui = New(uiType);
        var pub = NGet(playerData, "publicData")!;
        var lrd = NGet(pub, "lastRoundData");
        var usedCards = lrd != null ? NGet(lrd, "usedCards") as System.Collections.IList : null;

        // Cultivation-scaling cards (e.g. Diligent Sword 1000054: +1 ATK per `otherParams[0]` cultivation)
        // read src.characterUI.exp at play time. The game sets that from publicData.lastRoundData.exp in
        // BattleCharacterUI.InitData (BattleCharacterUI.cs:179) — a UI method we don't run headless — so the
        // exp would stay 0 and the bonus reads 0 (silent under-damage). Seed the m_Exp backing field directly
        // (the `exp` property setter writes a TMP label -> NRE headless); the `exp` getter returns m_Exp.
        // (ORACLE_NO_EXP_SEED=1 disables this hand-seed to verify the data-driven `survive InitData` path
        //  recovers exp automatically — once proven, the hand-seed is retired in favor of the general path.)
        if (Environment.GetEnvironmentVariable("ORACLE_NO_EXP_SEED") != "1")
            if (lrd != null) try { NSet(ui, "m_Exp", Convert.ToInt32(NGet(lrd, "exp") ?? 0)); } catch { }

        // Build m_KeYinItems parallel to lastRoundData.usedKeYinCards. The keYinItems getter, when the
        // field is null, walks m_KeYinItemContainer.childCount (scene Transform, null headless) -> NRE;
        // and combat indexes keYinItems[currentUsingKeYinCardIndex] parallel to battleKeYinCards (=
        // usedKeYinCards, BattleExecuter.cs:2438) -> ArgOutOfRange on an empty list. So seed a non-null
        // List and fill one KeYinItem per used keyin card, with its KeYinCardConfig (the only gameplay
        // state combat reads: keYinItem.cardConfig). KeYinItem is fully nopped, so set the backing fields
        // directly (cardConfig/index) instead of calling the nopped InitData. Config lookup mirrors
        // KeYinItem.InitData -> KeYinCardFactory.FindCardConfig(cardId).
        var keyinField = FindField(uiType, "m_KeYinItems");
        var keyinList = keyinField != null ? Activator.CreateInstance(keyinField.FieldType) : null;
        if (keyinList != null) NSet(ui, "m_KeYinItems", keyinList);
        var keyinType = game.GetType("KeYinItem");
        var findKeYinCfg = game.GetType("KeYinCardFactory")?.GetMethod("FindCardConfig", BindingFlags.Public | BindingFlags.Static);
        var usedKeYin = lrd != null ? NGet(lrd, "usedKeYinCards") as System.Collections.IList : null;
        if (keyinList != null && keyinType != null && usedKeYin != null)
        {
            int ki = 0;
            foreach (var c in usedKeYin)
            {
                int id = Convert.ToInt32(c);
                var item = New(keyinType);
                var cfg = id != 0 ? findKeYinCfg?.Invoke(null, new object[] { id }) : null;
                if (cfg != null) NSet(item, "cardConfig", cfg);
                NSet(item, "index", ki++);
                ListAdd(keyinList, item);
            }
        }
        var battleCardItems = NGet(ui, "battleCardItems")!;
        var refreshSpecial = ciType.GetMethods(ANY).FirstOrDefault(m => m.Name == "RefreshSpecialCard" && m.GetParameters().Length == 2);
        var findCardCfg = game.GetType("CardFactory")!.GetMethod("FindCardConfig", BindingFlags.Public | BindingFlags.Static);
        int grid = 0;
        if (usedCards != null)
            foreach (var c in usedCards)
            {
                int id = Convert.ToInt32(c);
                var ci = New(ciType);
                // CardItem.Upgrade (fate/talent card upgrades) does compSystem.Get<MentorMarkComponent>();
                // compSystem is null on our hand-built items -> NRE. Construct a real ComponentSystem so
                // Get returns null cleanly (the MentorMark removal is meta, not combat). Prefer the
                // owner-arg ctor (initializes its component table), fall back to parameterless.
                var compField = FindField(ciType, "<compSystem>k__BackingField") ?? FindField(ciType, "compSystem");
                if (compField != null && NGet(ci, "compSystem") == null)
                {
                    object? cs = null;
                    try { cs = Activator.CreateInstance(compField.FieldType, ci); } catch { }
                    if (cs == null) try { cs = Activator.CreateInstance(compField.FieldType); } catch { }
                    NSet(ci, "compSystem", cs ?? New(compField.FieldType));
                }
                var cardInfo = NGet(ci, "cardInfo"); if (cardInfo != null) NSet(cardInfo, "id", id);
                var cfg = findCardCfg!.Invoke(null, new object[] { id });
                var cfgClone = cfg != null ? cfg.GetType().GetMethod("Clone")?.Invoke(cfg, null) : null;
                if (cfg != null) NSet(ci, "sourceCardConfig", cfg);
                if ((cfgClone ?? cfg) != null) NSet(ci, "cardConfig", cfgClone ?? cfg);
                NSet(ci, "showInBattle", true); NSet(ci, "gridNumber", grid++);
                NSet(ci, "hadUsed", false); NSet(ci, "skip", false);
                if (refreshSpecial != null) { try { refreshSpecial.Invoke(ci, new object[] { pub, false }); } catch (Exception rsx) { if (Environment.GetEnvironmentVariable("ORACLE_DIAG_REFRESH") == "1") { var ix = rsx.InnerException ?? rsx; Console.WriteLine($"      [RefreshSpecialCard threw on card {NGet(NGet(ci,"cardConfig")!,"id")}]: {ix.GetType().Name}: {ix.Message.Split('\n')[0]}"); var st = new System.Diagnostics.StackTrace(ix, false); foreach (var f in (st.GetFrames() ?? Array.Empty<System.Diagnostics.StackFrame>()).Take(8)) { var m = f.GetMethod(); Console.WriteLine($"          at {m?.DeclaringType?.FullName}.{m?.Name}+IL_{f.GetILOffset():X4}"); } } } }
                ListAdd(battleCardItems, ci);
            }
        return ui;
    }

    // Auto-load EVERY config .dat into its backing static List<TConfig> field (discovered by reflection),
    // skipping the canonical ones already set. One pass maps config-element-type -> static List field across
    // all game types, then each <Name>.dat is loaded into List<Name>'s field. Makes the runner load all 128
    // game configs so no season/character's combat path reads an empty table; new configs auto-covered.
    static void LoadAllConfigsAuto(Assembly game, string configsDir, System.Collections.Generic.HashSet<string> already)
    {
        // Config List<T> statics live on ConfigManager (the few that don't — TalentResonance/KeYin — are in
        // the hardcoded list already). Search ONLY ConfigManager's fields: enumerating game.GetTypes() force-
        // loads every type incl. a broken UniRx facade (TypeLoadException) and isn't needed here.
        var fieldByElem = new System.Collections.Generic.Dictionary<Type, System.Reflection.FieldInfo>();
        var cfgMgrT = game.GetType("ConfigManager");
        if (cfgMgrT != null)
            foreach (var f in cfgMgrT.GetFields(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
            {
                var ft = f.FieldType;
                if (!ft.IsGenericType || ft.GetGenericTypeDefinition() != typeof(System.Collections.Generic.List<>)) continue;
                var elem = ft.GetGenericArguments()[0];
                if (!fieldByElem.ContainsKey(elem)) fieldByElem[elem] = f;   // first wins
            }
        int loaded = 0, nofield = 0, fail = 0;
        foreach (var dat in Directory.GetFiles(configsDir, "*.dat").OrderBy(x => x))
        {
            var name = Path.GetFileNameWithoutExtension(dat);
            if (already.Contains(name)) continue;
            var cfgType = game.GetType($"Proto.{name}") ?? game.GetType(name);
            if (cfgType == null) continue;
            if (!fieldByElem.TryGetValue(cfgType, out var field)) { nofield++; continue; }
            try
            {
                if (field.GetValue(null) is System.Collections.ICollection cur && cur.Count > 0) continue;  // already populated
                field.SetValue(null, LoadConfigList(game, name, configsDir));
                loaded++;
            }
            catch { fail++; }
        }
        Console.WriteLine($"  [auto-config] loaded {loaded} extra config lists ({nofield} no static List field, {fail} load-fail)");
    }

    // Read configsDir/{name}.dat ourselves and feed it to the game's own deserializer
    // (ConfigLoader.LoadWithTextAsset<T>: xresloader_datablocks -> per-entry proto). This bypasses the
    // Addressables facade (whose async LoadAssetAsync signature CoreClr binds too strictly to match).
    static object LoadConfigList(Assembly game, string configTypeName, string configsDir)
    {
        var cfgT = game.GetType($"Proto.{configTypeName}") ?? game.GetType(configTypeName)
                   ?? throw new Exception($"config type {configTypeName} not found");
        var datPath = Path.Combine(configsDir, configTypeName + ".dat");
        if (!File.Exists(datPath)) throw new Exception($"{Path.GetFileName(datPath)} missing");
        var textAsset = new UnityEngine.TextAsset(File.ReadAllBytes(datPath));
        var loader = game.GetType("ConfigLoader") ?? throw new Exception("ConfigLoader not found");
        var lwt = loader.GetMethod("LoadWithTextAsset", BindingFlags.NonPublic | BindingFlags.Static)
                  ?? throw new Exception("ConfigLoader.LoadWithTextAsset not found");
        return lwt.MakeGenericMethod(cfgT).Invoke(null, new object[] { textAsset })!;
    }

    static object? GetStatic(Type t, string field)
    {
        foreach (var name in new[] { field, $"<{field}>k__BackingField" })
        { var f = t.GetField(name, ANY_STATIC); if (f != null) return f.GetValue(null); }
        return t.GetProperty(field, ANY_STATIC)?.GetValue(null);
    }

    // Key a config list into a ConfigManager dictionary (cardConfigDict by id, levelConfigDict by level).
    // The dict key type may be an enum (e.g. Dictionary<Level,LevelConfig>); cast the field value to
    // the dict's actual key type so set_Item binds correctly.
    static void BuildDict(Type cfgMgr, string dictName, object list, string keyField)
    {
        var dict = GetStatic(cfgMgr, dictName);
        if (dict == null) { Console.WriteLine($"    dict {dictName}: NOT FOUND"); return; }
        var dictType = dict.GetType();
        var setItem = dictType.GetMethod("set_Item")!;
        // Get the declared key type from Dictionary<K,V> so enums are passed as the right type.
        var keyType = dictType.IsGenericType ? dictType.GetGenericArguments()[0] : typeof(int);
        int n = 0;
        foreach (var item in (System.Collections.IEnumerable)list)
        {
            var keyRaw = item.GetType().GetField(keyField)?.GetValue(item);
            if (keyRaw == null) continue;
            // Convert to the dict's key type (handles int→int identity and int→enum cast).
            object key = keyType.IsEnum
                ? Enum.ToObject(keyType, Convert.ToInt32(keyRaw))
                : Convert.ChangeType(keyRaw, keyType);
            setItem.Invoke(dict, new object[] { key, item }); n++;
        }
        Console.WriteLine($"    dict {dictName}: {n} entries");
    }

    // ConfigManager.s_BuffCategoryMap (BuffType -> BuffCategory), built from buffConfigs (each has
    // type + category). Without it GetBuffCategory returns the enum default (Positive) and every
    // debuff is miscounted — the bug we fixed in the ILRuntime path; mirror it natively.
    static void BuildBuffCategoryMap(Type cfgMgr, object buffConfigs)
    {
        var map = GetStatic(cfgMgr, "s_BuffCategoryMap");
        if (map == null) { Console.WriteLine("    s_BuffCategoryMap: NOT FOUND"); return; }
        var setItem = map.GetType().GetMethod("set_Item")!;
        int n = 0;
        foreach (var c in (System.Collections.IEnumerable)buffConfigs)
        {
            var type = c.GetType().GetField("type")?.GetValue(c);
            var cat = c.GetType().GetField("category")?.GetValue(c);
            if (type == null || cat == null) continue;
            setItem.Invoke(map, new[] { type, cat }); n++;
        }
        Console.WriteLine($"    s_BuffCategoryMap: {n} entries");
    }

    // OpenManager.s_OpenDict : Dictionary<OpenType, List<OpenConfig>>, grouped by each config's `type`.
    // Mirrors what get_openDict builds from ConfigLoader.Load<OpenConfig>(), but fed from our own loader.
    static void BuildOpenDict(System.Reflection.Assembly game, object openConfigs)
    {
        var openMgr = game.GetType("OpenManager");
        if (openMgr == null) { Console.WriteLine("    s_OpenDict: OpenManager not found"); return; }
        var field = openMgr.GetField("s_OpenDict", ANY_STATIC);
        if (field == null) { Console.WriteLine("    s_OpenDict: field not found"); return; }
        var dictType = field.FieldType;                                  // Dictionary<OpenType, List<OpenConfig>>
        var listType = dictType.GetGenericArguments()[1];               // List<OpenConfig>
        var dict = Activator.CreateInstance(dictType)!;
        var containsKey = dictType.GetMethod("ContainsKey")!;
        var getItem = dictType.GetMethod("get_Item")!;
        var setItem = dictType.GetMethod("set_Item")!;
        var listAdd = listType.GetMethod("Add")!;
        int n = 0;
        foreach (var c in (System.Collections.IEnumerable)openConfigs)
        {
            var key = c.GetType().GetField("type")?.GetValue(c);
            if (key == null) continue;
            if (!(bool)containsKey.Invoke(dict, new[] { key })!)
                setItem.Invoke(dict, new[] { key, Activator.CreateInstance(listType) });
            var list = getItem.Invoke(dict, new[] { key });
            listAdd.Invoke(list, new[] { c }); n++;
        }
        field.SetValue(null, dict);
        Console.WriteLine($"    s_OpenDict: {n} entries");
    }

    // Generic grouped-dict builder (Dictionary<key, List<Config>> grouped by keyField) for a static dict
    // field on `owner` (e.g. ConfigManager.charAnimClipDict). Generalizes BuildOpenDict; the dict's own
    // declared K/V types drive key conversion (handles int and enum keys) so it works for any grouped table.
    static void BuildGroupedDict(Type owner, string dictName, object list, string keyField)
    {
        // Populate the EXISTING dict in place (the auto-property backing field is initonly + already a
        // non-null empty dict from the cctor, so SetValue would throw). Mirrors BuildDict's in-place fill.
        var dict = GetStatic(owner, dictName);
        if (dict == null)
        {
            var f = owner.GetField(dictName, ANY_STATIC) ?? owner.GetField($"<{dictName}>k__BackingField", ANY_STATIC);
            if (f == null) { Console.WriteLine($"    grouped dict {dictName}: NOT FOUND"); return; }
            dict = Activator.CreateInstance(f.FieldType)!;
            try { f.SetValue(null, dict); }
            catch { Console.WriteLine($"    grouped dict {dictName}: null + initonly, cannot seed"); return; }
        }
        var dictType = dict.GetType();                               // Dictionary<K, List<V>>
        var keyType = dictType.GetGenericArguments()[0];
        var listType = dictType.GetGenericArguments()[1];           // List<V>
        var containsKey = dictType.GetMethod("ContainsKey")!;
        var getItem = dictType.GetMethod("get_Item")!;
        var setItem = dictType.GetMethod("set_Item")!;
        var listAdd = listType.GetMethod("Add")!;
        int n = 0;
        foreach (var item in (System.Collections.IEnumerable)list)
        {
            var keyRaw = item.GetType().GetField(keyField)?.GetValue(item);
            if (keyRaw == null) continue;
            object key = keyType.IsEnum ? Enum.ToObject(keyType, Convert.ToInt32(keyRaw)) : Convert.ChangeType(keyRaw, keyType);
            if (!(bool)containsKey.Invoke(dict, new[] { key })!)
                setItem.Invoke(dict, new[] { key, Activator.CreateInstance(listType) });
            listAdd.Invoke(getItem.Invoke(dict, new[] { key }), new[] { item }); n++;
        }
        Console.WriteLine($"    grouped dict {dictName}: {n} entries");
    }

    // Place a loaded config list into a static List<Proto.{configName}> field if one exists on a likely
    // owner type (many configs need only this; dict-only tables like CharacterAnimClipConfig return false).
    static bool TryPlaceConfigList(System.Reflection.Assembly game, string configName, object list)
    {
        var elemType = game.GetType($"Proto.{configName}");
        if (elemType == null) return false;
        var listType = typeof(System.Collections.Generic.List<>).MakeGenericType(elemType);
        foreach (var ownerName in new[] { "ConfigManager", "CardFactory", "KeYinCardFactory", "TalentResonancePanel", "OpenManager" })
        {
            var ot = game.GetType(ownerName);
            var f = ot?.GetFields(ANY_STATIC).FirstOrDefault(x => x.FieldType == listType);
            if (f != null) { f.SetValue(null, list); return true; }
        }
        return false;
    }

    static bool SetStatic(Type t, string field, object? val)
    {
        foreach (var name in new[] { field, $"<{field}>k__BackingField" })
        {
            var f = t.GetField(name, ANY_STATIC);
            if (f != null) { f.SetValue(null, val); return true; }
        }
        var p = t.GetProperty(field, ANY_STATIC);
        var setter = p?.GetSetMethod(true);
        if (setter != null) { setter.Invoke(null, new[] { val }); return true; }
        return false;
    }
}
