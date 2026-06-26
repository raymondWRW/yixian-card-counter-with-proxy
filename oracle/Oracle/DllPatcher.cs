// Cecil IL bytecode patcher — strips visual/UI method bodies from the game DLL
// before ILRuntime loads it. Replaces rendering code with minimal state-only logic.
//
// This runs ONCE at startup. The patched DLL lives only in memory.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using ILRuntime.Mono.Cecil;
using ILRuntime.Mono.Cecil.Cil;

namespace YiXianOracle;

public static class DllPatcher
{
    static int _patchCount = 0;
    static bool _handNops = true;   // gated by ORACLE_HAND_NOPS; when false, NopType/StubVisualType no-op (doctor re-derives them)
    // ORACLE_EXPORT_HANDFIXES=<path>: record every method the hand visual-nop/stub layer touches as an
    // auto_patch entry and write it out — so the hand C# list can be replaced by machine-generated DATA.
    static readonly List<(string type, string method, string action)> _exportFixes = new();
    static bool _exporting = false;
    // ORACLE_HAND_SKIP="Type.Method,Type2.Method2,...": leave these SPECIFIC methods UN-nopped/un-stubbed while
    // the rest of the hand layer stays ON — so incremental migration can remove ONE hand fix at a time and have
    // auto_heal re-derive it as data WITH the 100% parity signal intact (which instantly rejects a bad patch).
    static readonly HashSet<string> _handSkip = new(
        (Environment.GetEnvironmentVariable("ORACLE_HAND_SKIP") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries));

    // ─────────────────────────────────────────────────────────────────────────────────────────────
    // NATIVE pre-load patcher. CoreCLR loads raw PE bytes (no post-load IL access like ILRuntime's
    // ILType.TypeDefinition, and no AbsorbVisualNulls interpreter hook), so the visual methods must be
    // nopped in the BYTES before Assembly.Load. This mirrors PatchLoadedAssembly's patch list, but
    // resolves every type from the Cecil module + the COMPLETE generated facades (facades-gen) — the
    // old deprecated Patch() pointed its resolver at the incomplete hand-written facades and so failed
    // to resolve types like LanguageType when writing the module back out.
    // ─────────────────────────────────────────────────────────────────────────────────────────────
    public static byte[] PatchForNative(byte[] dllBytes, params string[] facadeSearchDirs)
    {
        _patchCount = 0;
        var resolver = new DefaultAssemblyResolver();
        foreach (var d in facadeSearchDirs) if (Directory.Exists(d)) resolver.AddSearchDirectory(d);
        // Never fail: any unresolved reference becomes an empty stand-in assembly. With facades-gen on
        // the search path this rarely fires, but it keeps Module.Write from throwing on stragglers.
        resolver.ResolveFailure += (s, r) => AssemblyDefinition.CreateAssembly(
            new AssemblyNameDefinition(r.Name, r.Version ?? new Version(0, 0)), r.Name, ModuleKind.Dll);
        var module = ModuleDefinition.ReadModule(new MemoryStream(dllBytes),
            new ReaderParameters { ReadWrite = false, InMemory = true, AssemblyResolver = resolver, ReadSymbols = false });

        // Hand-written fix surface (nops / stubs / bespoke IL rewrites). GATED so we can run with it OFF
        // (ORACLE_HAND_FIXES=0) and have oracle_doctor rebuild the equivalent set as DATA in auto_patch.json
        // — the migration path to ZERO handcrafted fixes. Infrastructure (huiHe/trace) + AutoPatch.Apply stay on.
        // See memory-bank/docs/oracle-consolidation-charter.md (agent division of labor + the two goals:
        // zero hand-written conversion, and capturing animation events for the web battle viewer).
        bool handFixes = Environment.GetEnvironmentVariable("ORACLE_HAND_FIXES") != "0";
        // Finer gate: ORACLE_HAND_NOPS=0 turns off ONLY the visual NopType/StubVisualType layer (the bulk that
        // the doctor re-derives as data) while the bespoke Patch*Module reconstructions + cctor nops stay ON —
        // so auto_heal heals the visual layer against a CORRECT-COMBAT baseline (not from fully-broken zero).
        _handNops = handFixes && Environment.GetEnvironmentVariable("ORACLE_HAND_NOPS") != "0";
        _exporting = !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("ORACLE_EXPORT_HANDFIXES"));
        _exportFixes.Clear();
        if (handFixes) {
        // Trimmed to the load-bearing subset (full-corpus validated): the 12 dropped methods (RefreshAllBuff,
        // UpdateStatusBarPos, ShowDamageEffect/HealEffect, PlayHurtAnimation, RefreshCardScroll, UpdateCardUI,
        // PrepareILRComponent, IsAllCardShown/2, FaceUpAllCards, RefreshQiShiShangXian) run harmlessly un-nopped
        // with complete facades. (InitData full-corpus skip-tested obsolete -> trimmed.)
        NopType(module, "BattleCharacterUI", new[] {
            "set_hp", "set_maxHp", "set_def", "set_anima",
            "SetTipoUI", "RefreshBuff",
            "SetVisible", "SetLifeLabel", "ShowBattleCards" });
        // (set_tempLife — the life-resource shield, gameplay stored only on the UI — is now handled by the general
        //  MOCK PASS, which rebuilds every UI setter as a pure backing-field store. The hand rewrite was deleted.)
        // CardItem.FlipCardFace — async card-flip animation (DOTween); visual. Nop it (returns default
        // UniTask). Other CardItem methods (Upgrade, gameplay write-backs) are left intact.
        // SetAnimaCost/SetAnimaColor only write the anima-cost label text/color (m_AnimaLabel, null
        // headless) — purely visual, store no gameplay state (the anima check reads cardConfig.anima
        // directly). Nop them.
        // SetGray (grays a card visually) drags in Spine.Unity.SkeletonGraphic, whose get_transform is an
        // explicit interface impl the facade generator leaves unimplemented (TypeLoad). Visual — nop it.
        // UpgradeEffect shows a "卡牌升级" float popup (visual) — nop it; the upgrade gameplay
        // (id+=10000, config reload, useType) is in Upgrade itself and stays intact.
        // RefreshAllTypeFlag does m_AllTypeFlag.SetActive(...) — m_AllTypeFlag is a UI GameObject (null
        // headless) -> NRE (crashed HD round dvmin0e-r13). Pure visual flag display; nop it.
        // RefreshAttatchKeyWordCardDesc refreshes the card's attached-keyword DESCRIPTION text; it can't
        // even JIT headless (TypeLoadException on UnityEngine.Matrix4x4, missing from the facade) so it
        // throws whenever a card with attached keywords is set up/played — corrupting fate-197 hexagram
        // rounds (dvmt20a-r14 +286, dvmin0e-r13 -173). Visual desc only; nop it.
        // ResetDescription/SetKeywordGray/SetNameLabel set TMP_Text labels + use Matrix4x4/ProfilerMarker/
        // TMPro types that TypeLoad-fault headless — and they're called DURING card play (desc refresh), so
        // the fault aborted the play BEFORE its gameplay ran (e.g. Li Man's stance never toggled). Purely
        // visual -> nop so the play completes.
        NopType(module, "CardItem", new[] { "SetAnimaCost", "ShowCardInBattle", "SetGray", "UpgradeEffect", "RefreshAllTypeFlag", "ResetDescription", "SetKeywordGray" });  // trimmed: 5 obsolete dropped (full-corpus validated)
        // CardItemBase visual: set_interactable (UI raycast flag), ResetLocation (return-to-hand tween).
        // InitParent just stores m_OriginParent/m_RootParent + m_Transform.SetParent (pure visual UI
        // parenting); m_Transform is null on the ctor-skipped KeYinCardItem Spawn stub -> NRE. Nop it
        // (safe for real CardItems too — no gameplay state).
        NopType(module, "CardItemBase", new[] { "RegisterEvent", "ResetLocation", "InitParent", "InitLocation" });
        // BattleCharacter.Cast plays the cast animation (visual); the gameplay effect is in CardActionBase.
        // OnBattleLose is a post-battle handler whose visual NRE would crash the process post-result; nop it.
        // Cast/EnableDemonEffect are gameplay-coupled (Cast gates damage application). MoveTo/ShowDeathDamage/
        // OnBattleWin were full-corpus skip-tested OBSOLETE with complete facades (12401/12405, identical to
        // baseline) and trimmed — they run harmlessly un-nopped now.
        NopType(module, "BattleCharacter", new[] { "EnableDemonEffect", "Cast", "OnBattleLose" });
        // ProjectUtils audio helpers (PlayCharacterSound -> CheckResourceExist) are cosmetic SFX; nop.
        NopType(module, "ProjectUtils", new[] { "PlayCharacterSound" });  // trimmed: 2 obsolete dropped (full-corpus validated)
        // TmpFloatingText: gameplay mutators (ModifyHp/ModifyAnima/ModifyDef with showFloatText) do
        // TmpFloatingText.Create(...).SetText(...) for the damage popup. Stub it non-null (Create + the
        // fluent setters return non-null stubs) so the popup chain doesn't NRE and abort the mutator —
        // the ILRuntime path keeps Create returning a singleton for the same reason.
        StubVisualType(module, "TmpFloatingText");
        // (removed: HpBarTweenEffect / HpBarCalibrationEffect / DefItem / AnimaItem hand-nops — now OBSOLETE
        //  with complete facades; prune_hand_fixes.py validated that skipping them holds parity across all
        //  seasons (12401/12405, identical to all-fixes-on). They run harmlessly un-nopped now.)
        NopType(module, "KeYinItem", new[] { "SetGray", "SetUnknown" });  // get_cardConfig full-corpus-validated obsolete, trimmed
        // KeYinCardItem is the VISUAL keyin-card object (extends CardItemBase); its methods (InitData,
        // TryInitPrefabPool, ...) reference unloadable visual deps and TypeLoad-fault when JIT'd headless.
        // The keyin gameplay runs in KeYinCardFunctions off the card config, so nop ALL its methods —
        // EXCEPT Spawn, which PatchKeYinCardItemSpawnModule (below) rewrites to return a ctor-skipped stub,
        // and InitData, which PatchKeYinCardItemInitDataModule (below) rewrites to its gameplay essentials
        // (it sets cardConfig — the value Execute/KeYinCardFunctions read; nopping it left cardConfig null
        // -> the IL_178C NRE that crash-aborted every Sigil/KeYin battle on turn 1).
        // get_cardConfig must stay live too: Execute (IL_1787 callvirt get_cardConfig) and
        // KeYinCardFunctions read the config back THROUGH the getter — a nopped getter returns null
        // regardless of the backing field, re-introducing the same IL_178C NRE.
        NopType(module, "KeYinCardItem", new[] { "ShowCardInBattle" });  // trimmed; Spawn/InitData/get_cardConfig still handled by bespoke patches
        // Animator: nop everything except the Transform-returning anchor getters, which combat reads as
        // animator.hitPoint/floatTextPoint/effectPoint.position. The ILRuntime path sets those fields to
        // dummy transforms; natively the fields are null, so STUB the getters to return non-null
        // Transforms (else .position NREs inside ModifyHp/Attack).
        // TRIMMED (prune_hand_fixes.py + full-corpus skip-test): of the animator's ~58 previously-nopped
        // methods, only these few are load-bearing headless — the rest run harmlessly with complete facades
        // (their FX-positioning reads are gated behind isVisible=false, so the un-stubbed anchor getters that
        // now return null are never dereferenced). get_hitPoint stays STUBBED (combat reads hitPoint.position).
        NopType(module, "CharacterBattleAnimator", new[] { "AddAnimation", "RefreshWithBattlePlayerData", "Reset", "SetIsReadyLayer", "SetVisible", "get_facingDirection" });
        StubVisualType(module, "CharacterBattleAnimator", new[] { "get_hitPoint" });
        PatchAnimatorPoolSpawnModule(module);
        // Spawn/InitData populate the mirror (keYinItems[i].cardConfig) at battle start — keep them even in
        // the skip-experiment, since the real InitData's Clone<KeYinCardConfig> returns null headless. Only the
        // swap/levelUp gameplay rewrites are gated, to prove survive+callback-firing reproduces them.
        PatchKeYinCardItemSpawnModule(module);
        PatchKeYinCardItemInitDataModule(module);
        // GENERIC cardConfig fix (now the DEFAULT, replacing the bespoke swapKeYin/levelUpKeYin rewrites): make
        // KeYinItem.get_cardConfig read the live model (+ runner __owner linking + callback-firing for the swap's
        // OnComplete writes). The ORIGINAL swap/levelUpKeYin then run correctly. Validated == bespoke: KeYin 24/24
        // + 146/146 across 151 Sigil fixtures, HD 196/196, Dream 0-mismatch, full corpus 2642. (ORACLE_KEYIN_REDIRECT
        // historical flag; this is unconditional now.)
        PatchKeYinCardConfigRedirectModule(module);
        // The ORIGINAL swap/levelUpKeYin call keYinItem.InitData(id)/SetGray() to re-sync the visual mirror —
        // pure-visual methods that NRE headless, throwing out of levelUpKeYin (sigil never levels) and the swap
        // callback. The redirect reads the model, not the backing, so neutralize them.
        NopType(module, "KeYinItem", new[] { "InitData", "SetGray" });
        PatchLazyCardInfoModule(module);
        if (Environment.GetEnvironmentVariable("ORACLE_DEBUG_XS") == "1") PatchDebugExecuteEffectModule(module);
        // (removed: BattleExecuter.OnHit nop — obsolete with complete facades, full-corpus validated)
        // GetCharacterAnimClipTypeConfig reads the (unloaded) anim-clip config list and string-splits a
        // null prefix -> NRE. It only drives animation clip selection (cosmetic). Return a non-null stub
        // config so callers don't NRE on the result either.
        // (removed: ConfigManager.GetCharacterAnimClipTypeConfig stub — OBSOLETE with complete facades, validated)
        // (removed: CardItem.InitData nop — full-corpus skip-tested OBSOLETE with complete facades + the
        //  bespoke CardItem config-writeback/upgrade-reload/transform-init patches below; runs harmlessly.)
        PatchCardItemConfigWritebackModule(module);
        PatchCardItemUpgradeReloadModule(module);
        PatchCardItemTransformInitDataModule(module);
        // Panel/component lookups: return NON-NULL uninitialized stubs (not null) so the visual object
        // graph Execute's shell walks (panel.SetBlockActive, panel.battleLayer.*) never null-derefs —
        // native has no AbsorbVisualNulls to swallow it.
        // get_transform returns null headless; Execute positions characters via leftCharacter.transform
        // .set_localPosition (cosmetic). Return a non-null Transform stub so the callvirt doesn't NRE.
        StubVisualType(module, "ILRComponentBase", new[] { "FindObject", "get_transform" });
        StubVisualType(module, "ILRPanelBase", new[] { "FindILRPanel" });
        // BattlePanel is touched directly by Execute's shell (SetBlockActive, battleLayer access). Stub
        // every method: ref-getters return non-null stubs, the rest no-op.
        // (removed: BattlePanel stub — OBSOLETE with complete facades; validated parity-neutral across seasons)
        // BattleCharacterUI sub-element getters (defItem/animaItem/keYinItem/tipoItem) are null headless;
        // gameplay mutators (ModifyDef/ModifyAnima/...) read e.g. defItem.transform for FX positioning.
        // Stub them non-null. NOT battleCardItems (the real deck list the gameplay reads) — left intact.
        // (get_keYinItems is handled instead by pre-seeding its m_KeYinItems backing field in
        // NativeRunner.BuildCharacterUI — the getter only NREs because it walks a null m_KeYinItemContainer
        // when the field is null; a non-null empty field short-circuits that. A Cecil newobj-List stub here
        // TypeLoad-faulted instead, so the field-seed is the right fix.)
        StubVisualType(module, "BattleCharacterUI", new[] { "get_defItem", "get_keYinItem", "get_tipoItem", "get_lifeItem" });  // get_animaItem full-corpus-validated obsolete, trimmed
        // Native adds OnEnd / the camera+scene visual methods (ILRuntime absorbs their NREs generically;
        // native has no absorb layer, so they must be nopped here). OnEnd runs AFTER the turn loop, so
        // nopping its visual cleanup doesn't affect the combat result (hp/turns already settled).
        NopType(module, "BattleExecuter", new[] { "AdjustVirtualCameraSize", "SetVisible", "OnEnd" });
        // get_isJudge chains GameClientUtil.get_client() (null s_Client headless) -> get_uid() (NRE).
        // Replay records are player battles, not judge sessions, so isJudge is false (the ILRuntime path
        // reaches the same answer via absorb: null uid -> IsJudge(null) -> false). Nop it -> default false.
        NopType(module, "BattleManager", new[] { "SwitchCamera", "get_isJudge" });
        NopType(module, "SceneLoader", new[] { "get_isLoading" });
        // OpenManager: NativeRunner.BuildOpenDict pre-loads real OpenConfig.dat into s_OpenDict, so the
        // real IsOpen / get_openDict / GetOpenConfig / IsOpenNormal path runs correctly natively (no
        // segfault — that was ILRuntime-only). DO NOT nop or rewrite these methods here; the real per-
        // record flags are loaded and accurate. (The ILRuntime path still nops + patches IsOpen because
        // ILRuntime's interpreter segfaults on the config walk; the native JIT does not.)
        } // end handFixes block 1
        // ── infrastructure (ALWAYS on — not fixes): turn-counter exposure + per-turn trace hooks ──
        PatchExposeHuiHe(module);
        PatchTraceHooks(module);
        if (Environment.GetEnvironmentVariable("ORACLE_TRACE_CARDS") == "1") PatchTraceCardPlaysModule(module);
        if (Environment.GetEnvironmentVariable("ORACLE_DBG_CWX") == "1") PatchDebugCheckWuXingModule(module);
        if (handFixes) {
        PatchNetworkExtensionsClone(module);
        NopCctorModule(module, "GameClientUtil");
        NopCctorModule(module, "NetworkExtensions");
        // GameDataManager.cctor news up a pile of UniRx ReactiveProperty<int> meta-currency fields
        // (xianYu/caiMo/...) irrelevant to combat; one throws headless -> TypeInitializationException
        // that poisons every static access. Nop it (combat never reads those fields).
        NopCctorModule(module, "GameDataManager");
        // TranslateUtil: card/buff/talent name lookups for float-text popups. They read
        // InternalSettingsManager.settings.language (null headless) -> NRE. These are purely cosmetic
        // (display names in TmpFloatingText), never gameplay. Nop all translate getters so float-text
        // chains degrade to empty strings rather than faulting combat.
        // (removed: all 5 TranslateUtil.Get*Translate nops — obsolete with complete facades, full-corpus validated)
        // SettingsManager.cctor (audio/graphics player settings) throws headless; nop it + return a
        // non-null Settings stub from get_settings (combat reads it for cosmetic toggles).
        NopCctorModule(module, "SettingsManager");
        StubVisualType(module, "SettingsManager", new[] { "get_settings" });
        // ...and its data getters return non-null uninitialized stubs (replay combat uses the record's
        // p1/p2 data, not GameDataManager.gameData; these reads are cosmetic player-name/avatar lookups).
        StubVisualType(module, "GameDataManager", new[] { "get_gameData" });
        } // end handFixes block 2

        // DETECTOR (env ORACLE_PERTURB_MIRRORS=1): perturb the value every int VISUAL-MIRROR getter returns,
        // so a normal-vs-perturbed corpus diff reveals which rounds READ a mirror for gameplay (the gap-#2
        // stale-mirror class) — with ZERO mirror->model mapping. Visuals are supposed to be inert; if
        // perturbing one moves the result, combat depends on it.
        if (Environment.GetEnvironmentVariable("ORACLE_PERTURB_MIRRORS") == "1") PatchPerturbMirrorsModule(module);

        // Data-driven auto-patch (env ORACLE_AUTO_PATCH=<spec.json>; inert if unset). Runs LAST and restores
        // original bodies from dllBytes, so it's independent of the hand nops above — the path toward
        // replacing the hand nop+restore grind with algorithmic "restore original + survive-headless".
        var exportPath = Environment.GetEnvironmentVariable("ORACLE_EXPORT_HANDFIXES");
        if (!string.IsNullOrEmpty(exportPath))
        {
            var json = "[\n" + string.Join(",\n", _exportFixes
                .Select(f => $"  {{ \"type\": \"{f.type}\", \"method\": \"{f.method}\", \"sig\": \"\", \"action\": \"{f.action}\" }}")) + "\n]\n";
            File.WriteAllText(exportPath, json);
            Console.WriteLine($"  [native patch] exported {_exportFixes.Count} hand visual-fix entries -> {exportPath}");
        }
        // THE MOCK PASS (default; ORACLE_NO_MOCK_UI=1 disables): make every UI component a functional state cell —
        // rebuild each UI setter as a pure backing-field store (render dropped) so the engine's
        // characterUI.tempLife += x etc. lands. ONE structural rule (auto-detected across all UI setters), version-
        // agnostic — generalizes the hand set_tempLife rewrite. Validated == hand (full corpus 2642, HD 196/196).
        if (Environment.GetEnvironmentVariable("ORACLE_NO_MOCK_UI") != "1") AutoPatch.MockUiAccessors(module);
        AutoPatch.Apply(module, dllBytes, Environment.GetEnvironmentVariable("ORACLE_AUTO_PATCH"));
        // Animation/visual EVENT CAPTURE for the web battle viewer (env ORACLE_CAPTURE_ANIM=1; inert otherwise
        // so parity runs are untouched). Injects OracleAnim.Record(turn, "Type.Method") at the start of the
        // visual/animation methods — even when nopped — so the same real run emits a per-turn animation stream
        // the browser replays. See memory-bank/docs/oracle-consolidation-charter.md (goal 2).
        if (Environment.GetEnvironmentVariable("ORACLE_CAPTURE_ANIM") == "1") PatchAnimationCaptureModule(module);
        // Detector (env ORACLE_DETECT_NOPS=1): list nopped methods whose ORIGINAL body writes gameplay state
        // — i.e. overbroad nops that silently dropped gameplay (candidates for `action:"survive"`).
        if (Environment.GetEnvironmentVariable("ORACLE_DETECT_NOPS") == "1")
            foreach (var hit in AutoPatch.DetectOverbroadNops(dllBytes, module,
                new[] { "CardItem", "KeYinCardItem", "CardItemBase", "BattleCharacterUI", "BattleCharacter", "KeYinItem", "DefItem", "AnimaItem" }))
                Console.WriteLine($"  [detect-nop] overbroad nop (gameplay dropped): {hit}");

        var output = new MemoryStream();
        module.Write(output, new WriterParameters { WriteSymbols = false });
        Console.WriteLine($"  [native patch] applied {_patchCount} IL patches");
        var bytes = output.ToArray();
        var dumpPath = Environment.GetEnvironmentVariable("ORACLE_DUMP_PATCHED");
        if (!string.IsNullOrEmpty(dumpPath)) { File.WriteAllBytes(dumpPath, bytes); Console.WriteLine($"  [native patch] wrote patched DLL -> {dumpPath}"); }
        return bytes;
    }

    // Cecil IL disassembler for debugging (replaces the deleted FacadeGen.DumpMethodIL). Reads the raw DLL
    // (no resolver needed for instruction listing) and prints a method's IL, optionally only near an offset.
    public static void DumpMethodIL(string dllPath, string typeName, string methodName, int aroundOffset = -1)
    {
        var module = ModuleDefinition.ReadModule(dllPath, new ReaderParameters { ReadSymbols = false });
        var t = AllModuleTypes(module).FirstOrDefault(x => x.Name == typeName);
        var m = t?.Methods.FirstOrDefault(x => x.Name == methodName && x.HasBody);
        if (m == null) { Console.WriteLine($"  method {typeName}.{methodName} not found"); return; }
        Console.WriteLine($"=== {typeName}.{methodName} IL ({m.Body.Instructions.Count} instrs){(aroundOffset >= 0 ? $", near IL_{aroundOffset:X4}" : "")} ===");
        foreach (var ins in m.Body.Instructions)
        {
            if (aroundOffset >= 0 && Math.Abs(ins.Offset - aroundOffset) > 32) continue;
            var op = ins.Operand is MethodReference mr ? $"{mr.DeclaringType?.Name}.{mr.Name}"
                   : ins.Operand is FieldReference fr ? $"{fr.DeclaringType?.Name}.{fr.Name}"
                   : ins.Operand?.ToString();
            Console.WriteLine($"  IL_{ins.Offset:X4}: {ins.OpCode,-12} {op}");
        }
    }

    static IEnumerable<TypeDefinition> AllModuleTypes(ModuleDefinition m)
    {
        foreach (var t in m.Types) { yield return t; foreach (var n in NestedRec(t)) yield return n; }
    }
    static IEnumerable<TypeDefinition> NestedRec(TypeDefinition t)
    {
        foreach (var n in t.NestedTypes) { yield return n; foreach (var nn in NestedRec(n)) yield return nn; }
    }
    static TypeDefinition? FindTypeM(ModuleDefinition m, string name) =>
        AllModuleTypes(m).FirstOrDefault(t => t.Name == name);

    static void NopType(ModuleDefinition module, string typeName, string[]? methodNames, string[]? excludeNames = null)
    {
        if (!_handNops) return;   // ORACLE_HAND_NOPS=0: skip the hand visual-nop layer so the doctor re-derives it
        var type = FindTypeM(module, typeName);
        if (type == null) { Console.WriteLine($"  [native patch] WARN: type {typeName} not found"); return; }
        foreach (var method in type.Methods)
        {
            if (method.IsConstructor || method.Name == ".cctor") continue;
            if (methodNames != null && !methodNames.Contains(method.Name)) continue;
            if (excludeNames != null && excludeNames.Contains(method.Name)) continue;
            if (!method.HasBody) continue;
            if (_handSkip.Contains($"{typeName}.{method.Name}") || _handSkip.Contains($"{typeName}.*")) continue;   // incremental migration: leave un-nopped
            NopMethod(method);
            if (_exporting) _exportFixes.Add((typeName, method.Name, "nop"));
        }
    }

    static void NopCctorModule(ModuleDefinition module, string typeName)
    {
        var cctor = FindTypeM(module, typeName)?.Methods.FirstOrDefault(m => m.Name == ".cctor");
        if (cctor != null && cctor.HasBody) NopMethod(cctor);
    }

    // Native has no AbsorbVisualNulls hook, and `callvirt` null-checks the receiver, so nopping a
    // visual method body can't save a call made on a NULL visual object. The fix is to keep the visual
    // object GRAPH non-null: rewrite a method to return an UNINITIALIZED (ctor-skipped, side-effect-free)
    // non-null instance of its return type. Used for the panel/component lookups (FindILRPanel<T>, ...)
    // and for ref-returning getters on stubbed visual types, so chained `panel.layer.ui` stays non-null.
    internal static bool ReturnNonNullStub(ModuleDefinition module, MethodDefinition m)
    {
        if (!m.HasBody) return false;
        var rt = m.ReturnType;
        // GetUninitializedObject can't build interfaces/abstract types/strings/arrays — fall back to nop.
        bool concreteRef = rt.IsGenericParameter
            || (!rt.IsValueType && !rt.IsArray && rt.FullName != "System.Void" && rt.FullName != "System.String"
                && (rt.Resolve() is { IsInterface: false, IsAbstract: false }));
        if (!concreteRef) { NopMethod(m); return true; }
        var il = m.Body.GetILProcessor();
        m.Body.Instructions.Clear(); m.Body.ExceptionHandlers.Clear(); m.Body.Variables.Clear();
        // Prefer `newobj T()` when the (non-generic) return type has an accessible parameterless ctor —
        // that runs the facade's own ctor (e.g. Transform sets parent/localScale), giving a properly
        // initialized stub. Otherwise fall back to GetUninitializedObject (ctor-skipped) — needed for
        // game types (BattlePanel, ...) whose ctors would drag in visual init.
        // newobj only for FACADE types (safe hand-written ctors, e.g. Transform sets parent/scale).
        // GAME types (DefItem, BattlePanel, ...) have compiler-gen ctors that do visual init and throw —
        // use GetUninitializedObject (ctor-skipped) for those.
        MethodReference? ctor = null;
        if (!rt.IsGenericParameter)
        {
            var def = rt.Resolve();
            bool isGameType = def != null && def.Module == m.Module;
            var pc = isGameType ? null : def?.Methods.FirstOrDefault(c => c.IsConstructor && !c.IsStatic && c.Parameters.Count == 0 && (c.IsPublic || c.IsAssembly));
            if (pc != null) ctor = module.ImportReference(pc);
        }
        if (ctor != null)
        {
            il.Append(il.Create(OpCodes.Newobj, ctor));
            il.Append(il.Create(OpCodes.Ret));
        }
        else
        {
            var getTypeFromHandle = module.ImportReference(typeof(Type).GetMethod("GetTypeFromHandle", new[] { typeof(RuntimeTypeHandle) }));
            var getUninit = module.ImportReference(typeof(System.Runtime.CompilerServices.RuntimeHelpers)
                .GetMethod("GetUninitializedObject", new[] { typeof(Type) }));
            il.Append(il.Create(OpCodes.Ldtoken, rt));
            il.Append(il.Create(OpCodes.Call, getTypeFromHandle));
            il.Append(il.Create(OpCodes.Call, getUninit));
            il.Append(il.Create(rt.IsGenericParameter ? OpCodes.Unbox_Any : OpCodes.Castclass, rt));
            il.Append(il.Create(OpCodes.Ret));
        }
        _patchCount++;
        return true;
    }

    // Stub a whole visual UI type: ref-returning methods/getters return a non-null uninitialized stub
    // (so the graph stays non-null), everything else no-ops. Constructors/cctors are left intact so the
    // type can still be uninitialized-allocated. methodNames optionally limits which methods are touched.
    static void StubVisualType(ModuleDefinition module, string typeName, string[]? methodNames = null, string[]? excludeNames = null)
    {
        if (!_handNops) return;   // ORACLE_HAND_NOPS=0: skip the hand visual-stub layer so the doctor re-derives it
        var type = FindTypeM(module, typeName);
        if (type == null) { Console.WriteLine($"  [native patch] WARN: visual type {typeName} not found"); return; }
        foreach (var method in type.Methods)
        {
            if (method.IsConstructor || method.Name == ".cctor") continue;
            if (methodNames != null && !methodNames.Contains(method.Name)) continue;
            if (excludeNames != null && excludeNames.Contains(method.Name)) continue;
            if (!method.HasBody) continue;
            if (_handSkip.Contains($"{typeName}.{method.Name}") || _handSkip.Contains($"{typeName}.*")) continue;   // incremental migration: leave un-stubbed
            ReturnNonNullStub(module, method);
            if (_exporting) _exportFixes.Add((typeName, method.Name, "stub"));
        }
    }

    // Module variants of the gameplay-critical re-patches (card upgrade write-backs + physique fix).
    static void PatchCardItemConfigWritebackModule(ModuleDefinition module)
    {
        var typeDef = FindTypeM(module, "CardItem");
        if (typeDef == null) { Console.WriteLine("  [native patch] WARN: CardItem not found"); return; }
        var prop = typeDef.Properties.FirstOrDefault(p => p.Name == "cardConfig");
        var backing = prop?.GetMethod?.Body?.Instructions
            .FirstOrDefault(i => i.OpCode == OpCodes.Ldfld)?.Operand as FieldReference;
        var init = typeDef.Methods.FirstOrDefault(m =>
            m.Name == "InitData" && m.Parameters.Count > 0 && m.Parameters[0].ParameterType.Name == "CardConfig");
        if (backing == null || init == null || !init.HasBody) { Console.WriteLine("  [native patch] WARN: CardItem.InitData(CardConfig) writeback refs missing"); return; }
        var il = init.Body.GetILProcessor();
        init.Body.Instructions.Clear(); init.Body.ExceptionHandlers.Clear(); init.Body.Variables.Clear();
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Ldarg_1));
        il.Append(il.Create(OpCodes.Stfld, backing));
        il.Append(il.Create(OpCodes.Ret));
        _patchCount++;
    }

    static void PatchCardItemUpgradeReloadModule(ModuleDefinition module)
    {
        var typeDef = FindTypeM(module, "CardItem");
        if (typeDef == null) { Console.WriteLine("  [native patch] WARN: CardItem not found (upgrade-reload)"); return; }
        var cfgProp = typeDef.Properties.FirstOrDefault(p => p.Name == "cardConfig");
        var cfgBacking = cfgProp?.GetMethod?.Body?.Instructions
            .FirstOrDefault(i => i.OpCode == OpCodes.Ldfld)?.Operand as FieldReference;
        var upg = typeDef.Methods.FirstOrDefault(m => m.Name == "Upgrade");
        var getCardInfo = upg?.Body?.Instructions
            .FirstOrDefault(i => (i.OpCode == OpCodes.Call || i.OpCode == OpCodes.Callvirt)
                && i.Operand is MethodReference mr && mr.Name == "get_cardInfo")?.Operand as MethodReference;
        var idField = FindTypeM(module, "CardInfo")?.Fields.FirstOrDefault(f => f.Name == "id");
        var c19Instrs = FindTypeM(module, "Card_19")?.Methods.FirstOrDefault(m => m.Name == "UpdateCardInfo")?.Body?.Instructions;
        var findCfg = c19Instrs?.FirstOrDefault(i => (i.OpCode == OpCodes.Call || i.OpCode == OpCodes.Callvirt)
            && i.Operand is MethodReference fm && fm.Name == "FindCardConfig")?.Operand as MethodReference;
        var clone = c19Instrs?.FirstOrDefault(i => (i.OpCode == OpCodes.Call || i.OpCode == OpCodes.Callvirt)
            && i.Operand is MethodReference cm && cm.Name == "Clone")?.Operand as MethodReference;
        var init = typeDef.Methods.FirstOrDefault(m =>
            m.Name == "InitData" && m.Parameters.Count > 0 && m.Parameters[0].ParameterType.Name == "CardInfo");
        if (cfgBacking == null || getCardInfo == null || idField == null || findCfg == null || clone == null || init == null || !init.HasBody)
        { Console.WriteLine($"  [native patch] WARN: upgrade-reload refs missing (cfg={cfgBacking!=null} getCI={getCardInfo!=null} id={idField!=null} find={findCfg!=null} clone={clone!=null} init={init!=null})"); return; }
        var il = init.Body.GetILProcessor();
        init.Body.Instructions.Clear(); init.Body.ExceptionHandlers.Clear(); init.Body.Variables.Clear();
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Call, getCardInfo));
        il.Append(il.Create(OpCodes.Ldfld, idField));
        il.Append(il.Create(OpCodes.Call, findCfg));
        // NOTE: ILRuntime's version appends NetworkExtensions.Clone<CardConfig> (proto round-trip) for a
        // private copy, but the ProtobufParser facade is a stub (serialize -> "") so that clone is a
        // no-op/null on both paths. FindCardConfig(upgradedId) already returns the correct upgraded config
        // (the id was bumped by +10000), so assign it directly — no Clone (which natively NRE'd in the
        // stubbed ProtobufParser). `clone` is intentionally unused here.
        _ = clone;
        il.Append(il.Create(OpCodes.Stfld, cfgBacking));
        il.Append(il.Create(OpCodes.Ret));
        _patchCount++;
    }

    // CardItem.InitData(int cardId, CardUseType, int, Dictionary, string) is the card-TRANSFORM path: a card
    // re-inits itself AS a different card (cardConfig = FindCardConfig(cardId)). It's used by 五行流转
    // (Card_7000067), which transforms into its grid-neighbor card and re-executes. `NopType(CardItem,
    // InitData)` nopped it (its visual tail TypeLoad-faults headless), so the transform was a no-op ->
    // 五行流转 stayed itself and re-executed forever -> uncatchable STACK OVERFLOW (killed Sigil sweeps).
    // Re-patch it to the gameplay essentials, mirroring PatchKeYinCardItemInitDataModule + the unpatched IL
    // (set_useType · cardInfo.id=cardId · sourceCardConfig/cardConfig = FindCardConfig(cardId), no Clone —
    // the ProtobufParser round-trip stub returns null). The other InitData overloads stay nopped/writeback.
    static void PatchCardItemTransformInitDataModule(ModuleDefinition module)
    {
        var t = FindTypeM(module, "CardItem");
        if (t == null) { Console.WriteLine("  [native patch] WARN: CardItem not found (transform InitData)"); return; }
        var m = t.Methods.FirstOrDefault(x => x.Name == "InitData" && x.Parameters.Count == 5
            && x.Parameters[0].ParameterType.FullName == "System.Int32"
            && x.Parameters[1].ParameterType.Name == "CardUseType");
        if (m == null) { Console.WriteLine("  [native patch] WARN: CardItem.InitData(int,CardUseType,int,Dict,string) not found"); return; }
        var setUseType = FindTypeM(module, "CardItemBase")?.Methods.FirstOrDefault(x => x.Name == "set_useType");
        var getCardInfo = FindTypeM(module, "CardItemBase")?.Methods.FirstOrDefault(x => x.Name == "get_cardInfo");
        var cardInfoIdField = getCardInfo?.ReturnType.Resolve()?.Fields.FirstOrDefault(f => f.Name == "id");
        var findCardConfig = FindTypeM(module, "CardFactory")?.Methods.FirstOrDefault(x => x.Name == "FindCardConfig" && x.IsStatic && x.Parameters.Count == 1);
        var cardCfgBacking = t.Properties.FirstOrDefault(p => p.Name == "cardConfig")?.GetMethod?.Body?.Instructions
            .FirstOrDefault(i => i.OpCode == OpCodes.Ldfld)?.Operand as FieldReference;
        var sourceCfgBacking = t.Properties.FirstOrDefault(p => p.Name == "sourceCardConfig")?.GetMethod?.Body?.Instructions
            .FirstOrDefault(i => i.OpCode == OpCodes.Ldfld)?.Operand as FieldReference;
        if (setUseType == null || getCardInfo == null || cardInfoIdField == null || findCardConfig == null
            || cardCfgBacking == null || sourceCfgBacking == null)
        { Console.WriteLine("  [native patch] WARN: CardItem transform-InitData refs missing — skipped"); return; }
        var il = m.Body.GetILProcessor();
        m.Body.Instructions.Clear(); m.Body.ExceptionHandlers.Clear(); m.Body.Variables.Clear();
        // set_useType(useType)
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Ldarg_2));
        il.Append(il.Create(OpCodes.Call, setUseType));
        // cardInfo.id = cardId
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Call, getCardInfo));
        il.Append(il.Create(OpCodes.Ldarg_1));
        il.Append(il.Create(OpCodes.Stfld, module.ImportReference(cardInfoIdField)));
        // sourceCardConfig = FindCardConfig(cardId)
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Ldarg_1));
        il.Append(il.Create(OpCodes.Call, findCardConfig));
        il.Append(il.Create(OpCodes.Stfld, sourceCfgBacking));
        // cardConfig = FindCardConfig(cardId)  (no Clone)
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Ldarg_1));
        il.Append(il.Create(OpCodes.Call, findCardConfig));
        il.Append(il.Create(OpCodes.Stfld, cardCfgBacking));
        il.Append(il.Create(OpCodes.Ret));
        _patchCount++;
    }

    // DIAGNOSTIC (env ORACLE_TRACE_CARDS=1): at CardActionBase.ExecuteEffect entry, if a round is being
    // traced (s_OracleTrace != null), emit a "PLAY" event into the SAME trace stream as the stat mutations
    // (recv=src so it gets the L/R side; a0=cardConfig.id; a1=cardConfig.attack). This labels each hit with
    // the card that caused it, so the per-turn trace can be walked card-by-card and each card's applied
    // values sanity-checked against its definition (no recording needed — internal-consistency check).
    static void PatchTraceCardPlaysModule(ModuleDefinition module)
    {
        var cab = FindTypeM(module, "CardActionBase");
        var ee = cab?.Methods.FirstOrDefault(x => x.Name == "ExecuteEffect" && x.HasBody);
        var getCfg = cab?.Methods.FirstOrDefault(x => x.Name == "get_cardConfig");
        var traceFld = FindTypeM(module, "BattleExecuter")?.Fields.FirstOrDefault(f => f.Name == "s_OracleTrace");
        var cfgT = getCfg?.ReturnType.Resolve();
        var idF = cfgT?.Fields.FirstOrDefault(f => f.Name == "id");
        var atkF = cfgT?.Fields.FirstOrDefault(f => f.Name == "attack");
        var invoke = module.ImportReference(typeof(Action<object, string, int, int>).GetMethod("Invoke"));
        if (ee == null || getCfg == null || traceFld == null || idF == null || atkF == null)
        { Console.WriteLine("  [native patch] WARN: trace-cards members missing"); return; }
        var il = ee.Body.GetILProcessor();
        var first = ee.Body.Instructions[0];
        void Ins(Instruction i) => il.InsertBefore(first, i);
        Ins(il.Create(OpCodes.Ldsfld, traceFld));
        Ins(il.Create(OpCodes.Brfalse, first));      // not tracing -> skip
        Ins(il.Create(OpCodes.Ldsfld, traceFld));
        Ins(il.Create(OpCodes.Ldarg_1));             // src (object recv -> L/R side)
        Ins(il.Create(OpCodes.Ldstr, "PLAY"));
        Ins(il.Create(OpCodes.Ldarg_0)); Ins(il.Create(OpCodes.Call, getCfg)); Ins(il.Create(OpCodes.Ldfld, module.ImportReference(idF)));
        Ins(il.Create(OpCodes.Ldarg_0)); Ins(il.Create(OpCodes.Call, getCfg)); Ins(il.Create(OpCodes.Ldfld, module.ImportReference(atkF)));
        Ins(il.Create(OpCodes.Callvirt, invoke));
        _patchCount++;
    }

    // DIAGNOSTIC (opt-in env ORACLE_DBG_CWX=1; inert otherwise): before each `ret` in
    // CardActionBase.CheckWuXing, print "CWX <jihuoEnumInt> -> <result>" — but only while a round is being
    // traced (s_OracleTrace != null), so it's quiet otherwise. Measured the WuXing damage-bonus gate for the
    // Five-Elements under-damage investigation: in bstvo21-r6 it returned True on ALL 7 calls, so the gate
    // is NOT the bug (the under-damage is in damage magnitude / 势 scaling, not WuXing activation/gating).
    // Kept as a reusable probe for the next WuXing dig.
    static void PatchDebugCheckWuXingModule(ModuleDefinition module)
    {
        var cab = FindTypeM(module, "CardActionBase");
        var m = cab?.Methods.FirstOrDefault(x => x.Name == "CheckWuXing" && x.IsStatic && x.HasBody);
        var traceFld = FindTypeM(module, "BattleExecuter")?.Fields.FirstOrDefault(f => f.Name == "s_OracleTrace");
        if (m == null || traceFld == null) { Console.WriteLine("  [native patch] WARN: CheckWuXing/traceFld not found (DBG_CWX)"); return; }
        var wrStr = module.ImportReference(typeof(Console).GetMethod("Write", new[] { typeof(string) }));
        var wrInt = module.ImportReference(typeof(Console).GetMethod("Write", new[] { typeof(int) }));
        var wrLineBool = module.ImportReference(typeof(Console).GetMethod("WriteLine", new[] { typeof(bool) }));
        var il = m.Body.GetILProcessor();
        foreach (var ret in m.Body.Instructions.Where(i => i.OpCode == OpCodes.Ret).ToList())
        {
            // stack at ret: [result(bool)]. Insert (gated by s_OracleTrace): print "CWX <jihuo> -> <result>".
            void Ins(Instruction i) => il.InsertBefore(ret, i);
            Ins(il.Create(OpCodes.Ldsfld, traceFld));
            Ins(il.Create(OpCodes.Brfalse, ret));            // not tracing -> straight to ret with [result]
            Ins(il.Create(OpCodes.Ldstr, "  CWX "));
            Ins(il.Create(OpCodes.Call, wrStr));
            Ins(il.Create(OpCodes.Ldarg_1));                 // jihuoWuXing (BuffType ~ int)
            Ins(il.Create(OpCodes.Call, wrInt));
            Ins(il.Create(OpCodes.Ldstr, " -> "));
            Ins(il.Create(OpCodes.Call, wrStr));
            Ins(il.Create(OpCodes.Dup));                     // dup result
            Ins(il.Create(OpCodes.Call, wrLineBool));
        }
        _patchCount++;
    }

    // The turn count `huiHeCount` is a hoisted local in the Execute async state machine
    // (<Execute>d__NN.<huiHeCount>5__NN) — inaccessible after Execute returns. Add a public static
    // BattleExecuter.s_OracleHuiHe and mirror every store of huiHeCount into it (dup; stsfld), so the
    // native runner can read the final turn count after the battle (parity with ILRuntime's OnTurnStarted
    // trace count — huiHeCount increments once per turn, so its last value IS the turn count).
    static void PatchExposeHuiHe(ModuleDefinition module)
    {
        var be = FindTypeM(module, "BattleExecuter");
        if (be == null) { Console.WriteLine("  [native patch] WARN: BattleExecuter not found (huiHe expose)"); return; }
        var fld = new FieldDefinition("s_OracleHuiHe", FieldAttributes.Public | FieldAttributes.Static, module.TypeSystem.Int32);
        be.Fields.Add(fld);
        // Find the Execute state machine by its hoisted huiHeCount field.
        TypeDefinition? sm = null; FieldDefinition? huiField = null;
        foreach (var t in AllModuleTypes(module))
        {
            var f = t.Fields.FirstOrDefault(x => x.Name.StartsWith("<huiHeCount>"));
            if (f != null) { sm = t; huiField = f; break; }
        }
        var moveNext = sm?.Methods.FirstOrDefault(m => m.Name == "MoveNext");
        if (moveNext == null || huiField == null || !moveNext.HasBody) { Console.WriteLine("  [native patch] WARN: Execute MoveNext / huiHeCount field not found"); return; }
        var il = moveNext.Body.GetILProcessor();
        var stores = moveNext.Body.Instructions.Where(i => i.OpCode == OpCodes.Stfld && (i.Operand as FieldReference)?.Name == huiField.Name).ToList();
        foreach (var st in stores)
        {
            // stack before stfld: [stateMachine, value]; dup the value, stash to the static, then stfld.
            il.InsertBefore(st, il.Create(OpCodes.Dup));
            il.InsertBefore(st, il.Create(OpCodes.Stsfld, fld));
        }
        _patchCount++;
        Console.WriteLine($"  [native patch] exposed huiHeCount via BattleExecuter.s_OracleHuiHe ({stores.Count} store sites)");
    }

    // NetworkExtensions.Clone<T> does a proto round-trip via DarkSun.Utility.ProtobufParser; the facades-gen
    // STUB ProtobufParser returns a null decode stream so Clone NREs, and Card_19/126/326.UpdateCardInfo
    // (which Clone the base config before evolving it) silently abort -> the Sword Embryo / Scrolls play at
    // BASE level (the embryo HD-parity bug). We can't override the whole DarkSun.Utility assembly (the
    // hand-written facade is missing types). Instead rewrite Clone to a self-contained round-trip through the
    // message's OWN working WriteTo/MergeFrom over a fresh wProtobuf.MessageStream (no ProtobufParser).
    //   T copy = new T(); var ws = new MessageStream(256); message.WriteTo(ws);
    //   copy.MergeFrom(new MessageStream(ws.ToByteArray())); return copy;
    static void PatchNetworkExtensionsClone(ModuleDefinition module)
    {
        var ne = FindTypeM(module, "NetworkExtensions");
        var clone = ne?.Methods.FirstOrDefault(m => m.Name == "Clone" && m.HasGenericParameters
            && m.GenericParameters.Count == 1 && m.Parameters.Count == 1 && m.HasBody);
        if (clone == null) { Console.WriteLine("  [native patch] WARN: NetworkExtensions.Clone<T> not found"); return; }
        var tparam = clone.GenericParameters[0];

        // IMessage (+ WriteTo/MergeFrom) from the original body's EncodeToBase64(IMessage) call.
        TypeReference? iMessage = clone.Body.Instructions
            .Select(i => i.Operand as MethodReference)
            .FirstOrDefault(mr => mr != null && mr.Name == "EncodeToBase64" && mr.Parameters.Count == 1)?.Parameters[0].ParameterType;
        var iMsgDef = iMessage?.Resolve();
        var writeTo = iMsgDef?.Methods.FirstOrDefault(m => m.Name == "WriteTo" && m.Parameters.Count == 1);
        var mergeFrom = iMsgDef?.Methods.FirstOrDefault(m => m.Name == "MergeFrom" && m.Parameters.Count == 1);
        if (iMessage == null || writeTo == null || mergeFrom == null) { Console.WriteLine($"  [native patch] WARN: Clone patch — IMessage/WriteTo/MergeFrom missing (im={iMessage!=null} wt={writeTo!=null} mf={mergeFrom!=null})"); return; }

        // wProtobuf.MessageStream + ctor(int) + ctor(byte[]) + ToByteArray() (ToByteArray may be on a base).
        var msRef = module.GetTypeReferences().FirstOrDefault(t => t.Name == "MessageStream" && t.Namespace == "wProtobuf")
                 ?? module.GetTypeReferences().FirstOrDefault(t => t.Name == "MessageStream");
        var msDef = msRef?.Resolve();
        var ctorInt = msDef?.Methods.FirstOrDefault(m => m.IsConstructor && m.Parameters.Count == 1 && m.Parameters[0].ParameterType.FullName == "System.Int32");
        var ctorBytes = msDef?.Methods.FirstOrDefault(m => m.IsConstructor && m.Parameters.Count == 1 && m.Parameters[0].ParameterType.IsArray);
        if (msRef == null || ctorInt == null || ctorBytes == null) { Console.WriteLine($"  [native patch] WARN: Clone patch — MessageStream refs missing (ms={msRef!=null} cI={ctorInt!=null} cB={ctorBytes!=null})"); return; }
        var msImp = module.ImportReference(msRef);
        // ToByteArray() is inherited from WriteStream; the patcher's resolver may only see a flat stub, so
        // build the MemberRef by hand on MessageStream (the runtime resolves it up the real hierarchy).
        var tb = new MethodReference("ToByteArray", new ArrayType(module.TypeSystem.Byte), msImp) { HasThis = true };

        var createInstT = new GenericInstanceMethod(module.ImportReference(typeof(System.Activator).GetMethod("CreateInstance", System.Type.EmptyTypes)));
        createInstT.GenericArguments.Add(tparam);
        var wt = module.ImportReference(writeTo); var mf = module.ImportReference(mergeFrom);
        var cInt = module.ImportReference(ctorInt); var cByt = module.ImportReference(ctorBytes);
        var iWrite = wt.Parameters[0].ParameterType; var iRead = mf.Parameters[0].ParameterType;

        var body = clone.Body;
        body.Instructions.Clear(); body.ExceptionHandlers.Clear(); body.Variables.Clear();
        var vCopy = new VariableDefinition(tparam); body.Variables.Add(vCopy);
        var vWs = new VariableDefinition(module.ImportReference(msRef)); body.Variables.Add(vWs);
        var p = body.GetILProcessor();
        // copy = new T()
        p.Append(p.Create(OpCodes.Call, createInstT)); p.Append(p.Create(OpCodes.Stloc, vCopy));
        // ws = new MessageStream(256)
        p.Append(p.Create(OpCodes.Ldc_I4, 256)); p.Append(p.Create(OpCodes.Newobj, cInt)); p.Append(p.Create(OpCodes.Stloc, vWs));
        // message.WriteTo((IWriteStream)ws)
        p.Append(p.Create(OpCodes.Ldarga_S, clone.Parameters[0]));
        p.Append(p.Create(OpCodes.Ldloc, vWs)); p.Append(p.Create(OpCodes.Castclass, iWrite));
        p.Append(p.Create(OpCodes.Constrained, tparam)); p.Append(p.Create(OpCodes.Callvirt, wt));
        // copy.MergeFrom((IReadStream) new MessageStream(ws.ToByteArray()))
        p.Append(p.Create(OpCodes.Ldloca_S, vCopy));
        p.Append(p.Create(OpCodes.Ldloc, vWs)); p.Append(p.Create(OpCodes.Callvirt, tb));
        p.Append(p.Create(OpCodes.Newobj, cByt)); p.Append(p.Create(OpCodes.Castclass, iRead));
        p.Append(p.Create(OpCodes.Constrained, tparam)); p.Append(p.Create(OpCodes.Callvirt, mf));
        // return copy
        p.Append(p.Create(OpCodes.Ldloc, vCopy)); p.Append(p.Create(OpCodes.Ret));
        _patchCount++;
        Console.WriteLine("  [native patch] rewrote NetworkExtensions.Clone<T> -> direct WriteTo/MergeFrom round-trip");
    }

    // Per-turn combat tracer: add a static BattleExecuter.s_OracleTrace (Action<object,string,int>) and
    // inject `s_OracleTrace?.Invoke(this, "<method>", <intArg>)` at the START of the gameplay mutators on
    // BattleCharacter (ModifyHp/ModifyDef/ModifyAnima/...). NativeRunner sets the delegate to record
    // (turn, side, tag, delta) so a diverging round's hp/def/anima change sequence is visible — the
    // replacement for the ILRuntime OnTrace hook we're retiring.
    static void PatchTraceHooks(ModuleDefinition module)
    {
        var be = FindTypeM(module, "BattleExecuter");
        var bc = FindTypeM(module, "BattleCharacter");
        if (be == null || bc == null) { Console.WriteLine("  [native patch] WARN: trace hooks skipped (types not found)"); return; }
        var actionT = module.ImportReference(typeof(Action<object, string, int, int>));
        var fld = new FieldDefinition("s_OracleTrace", FieldAttributes.Public | FieldAttributes.Static, actionT);
        be.Fields.Add(fld);
        var invoke = module.ImportReference(typeof(Action<object, string, int, int>).GetMethod("Invoke"));
        string[] traced = { "ModifyHp", "ModifyHpWithFx", "ModifyDef", "ModifyAnima", "ModifyMaxHp", "ModifyBuffValue", "SetBuffValue", "Attack" };
        int n = 0;
        // Helper: is a param int-stack-compatible (int32 / enum / bool) so we can push it as an int arg?
        static bool IsIntLike(ParameterDefinition p)
        {
            var ft = p.ParameterType;
            if (ft.FullName == "System.Int32" || ft.FullName == "System.Boolean") return true;
            try { return ft.Resolve()?.IsEnum == true; } catch { return false; }
        }
        foreach (var m in bc.Methods.Where(m => traced.Contains(m.Name) && m.HasBody && !m.IsStatic))
        {
            // Log the first two int-like params BY TYPE (not position): ModifyBuffValue(BuffType,delta) ->
            // (type,delta); ModifyHp(delta,..) -> (delta,0); Attack(BattleCharacter dst,int atk,int count)
            // -> (atk,count) so the embryo's resolved ATTACK value is visible. a1=0 if no 2nd int param.
            var intParams = m.Parameters.Where(IsIntLike).Take(2).ToList();
            if (intParams.Count == 0) continue;
            var il = m.Body.GetILProcessor();
            var first = m.Body.Instructions[0];
            // ldsfld s_OracleTrace; brfalse first; ldsfld; ldarg.0(this); ldstr name; ldarg.p0; ldarg.p1|ldc.0; callvirt Invoke
            il.InsertBefore(first, il.Create(OpCodes.Ldsfld, fld));
            il.InsertBefore(first, il.Create(OpCodes.Brfalse, first));
            il.InsertBefore(first, il.Create(OpCodes.Ldsfld, fld));
            il.InsertBefore(first, il.Create(OpCodes.Ldarg_0));
            il.InsertBefore(first, il.Create(OpCodes.Ldstr, m.Name));
            il.InsertBefore(first, il.Create(OpCodes.Ldarg, intParams[0]));
            il.InsertBefore(first, intParams.Count > 1 ? il.Create(OpCodes.Ldarg, intParams[1]) : il.Create(OpCodes.Ldc_I4_0));
            il.InsertBefore(first, il.Create(OpCodes.Callvirt, invoke));
            n++;
        }
        _patchCount++;
        Console.WriteLine($"  [native patch] trace hooks injected into {n} BattleCharacter mutators (BattleExecuter.s_OracleTrace)");
    }

    // Inject OracleAnim.Record(turn, "Type.Method") at the START of each visual/animation method, so the same
    // headless run that produces bit-exact gameplay ALSO emits a per-turn animation-event stream for the web
    // viewer. Runs AFTER the nops (the body is inert by now — we capture the EVENT, not rendered visuals) and
    // AFTER PatchExposeHuiHe (reads the turn from BattleExecuter.s_OracleHuiHe). Gated by ORACLE_CAPTURE_ANIM.
    static void PatchAnimationCaptureModule(ModuleDefinition module)
    {
        var huiFld = FindTypeM(module, "BattleExecuter")?.Fields.FirstOrDefault(f => f.Name == "s_OracleHuiHe");
        if (huiFld == null) { Console.WriteLine("  [native patch] WARN: anim capture skipped (s_OracleHuiHe not found)"); return; }
        var record = module.ImportReference(typeof(OracleAnim).GetMethod("Record"));
        var targets = new (string type, string[] methods)[]
        {
            // pure-visual / animation events (no numeric payload)
            ("BattleCharacter",   new[] { "Cast", "MoveTo", "ShowDeathDamage", "EnableDemonEffect" }),
            ("BattleCharacterUI", new[] { "PlayHurtAnimation", "ShowDamageEffect", "ShowHealEffect" }),
            ("CardItem",          new[] { "FlipCardFace", "UpgradeEffect", "ShowCardInBattle", "ReturnCardInBattle" }),
            // gameplay-numeric events — capture the delta(s) so the viewer can animate hp/anima/def bars
            ("BattleCharacter",   new[] { "ModifyHp", "ModifyHpWithFx", "ModifyDef", "ModifyAnima", "Attack" }),
        };
        static bool IsIntLike(ParameterDefinition p)
        {
            var ft = p.ParameterType;
            if (ft.FullName == "System.Int32" || ft.FullName == "System.Boolean") return true;
            try { return ft.Resolve()?.IsEnum == true; } catch { return false; }
        }
        int n = 0;
        foreach (var (tn, methods) in targets)
        {
            var t = FindTypeM(module, tn);
            if (t == null) continue;
            foreach (var m in t.Methods.Where(m => methods.Contains(m.Name) && m.HasBody && m.Body.Instructions.Count > 0))
            {
                var ints = m.Parameters.Where(IsIntLike).Take(2).ToList();   // first two int-like args (deltas), 0 if none
                var il = m.Body.GetILProcessor();
                var first = m.Body.Instructions[0];
                il.InsertBefore(first, il.Create(OpCodes.Ldsfld, huiFld));
                il.InsertBefore(first, il.Create(OpCodes.Ldstr, $"{tn}.{m.Name}"));
                il.InsertBefore(first, ints.Count > 0 ? il.Create(OpCodes.Ldarg, ints[0]) : il.Create(OpCodes.Ldc_I4_0));
                il.InsertBefore(first, ints.Count > 1 ? il.Create(OpCodes.Ldarg, ints[1]) : il.Create(OpCodes.Ldc_I4_0));
                il.InsertBefore(first, il.Create(OpCodes.Ldarg_0));          // the actor (`this`) -> Record resolves its charId
                il.InsertBefore(first, il.Create(OpCodes.Call, record));
                n++;
            }
        }
        _patchCount++;
        Console.WriteLine($"  [native patch] animation capture injected into {n} visual methods (OracleAnim.Record)");
    }

    static void PatchAnimatorPoolSpawnModule(ModuleDefinition module)
    {
        var poolType = FindTypeM(module, "CharacterBattleAnimatorPool");
        var animType = FindTypeM(module, "CharacterBattleAnimator");
        if (poolType == null || animType == null) { Console.WriteLine("  [native patch] WARN: animator pool/anim not found"); return; }
        var spawn = poolType.Methods.FirstOrDefault(m => m.Name == "Spawn" && m.IsStatic && m.Parameters.Count == 2);
        var ctor = animType.Methods.FirstOrDefault(m => m.IsConstructor && !m.IsStatic && m.Parameters.Count == 0);
        if (spawn == null || !spawn.HasBody || ctor == null) { Console.WriteLine("  [native patch] WARN: animator Spawn/ctor not found"); return; }
        // Build the CHARACTER-SPECIFIC animator (CharacterBattleAnimator_<charId>) via a factory delegate
        // NativeRunner sets from publicData.characterId — so casts like `src.animator as
        // CharacterBattleAnimator_4000005` succeed (Li Man's SwitchJiaShi line 5178 derefs that failed cast
        // -> NRE -> his stance never toggles). Falls back to the generic animator if the factory is unset.
        var be = FindTypeM(module, "BattleExecuter")!;
        var funcT = module.ImportReference(typeof(Func<object, object>));
        var fld = new FieldDefinition("s_OracleAnimatorFactory", FieldAttributes.Public | FieldAttributes.Static, funcT);
        be.Fields.Add(fld);
        var invoke = module.ImportReference(typeof(Func<object, object>).GetMethod("Invoke"));
        var il = spawn.Body.GetILProcessor();
        spawn.Body.Instructions.Clear(); spawn.Body.ExceptionHandlers.Clear(); spawn.Body.Variables.Clear();
        var fallback = il.Create(OpCodes.Pop);
        il.Append(il.Create(OpCodes.Ldsfld, fld));
        il.Append(il.Create(OpCodes.Dup));
        il.Append(il.Create(OpCodes.Brfalse, fallback));
        il.Append(il.Create(OpCodes.Ldarg_1));                       // publicData (BattlePlayerData)
        il.Append(il.Create(OpCodes.Callvirt, invoke));
        il.Append(il.Create(OpCodes.Castclass, animType));
        il.Append(il.Create(OpCodes.Ret));
        il.Append(fallback);                                         // delegate null -> generic animator
        il.Append(il.Create(OpCodes.Newobj, ctor));
        il.Append(il.Create(OpCodes.Ret));
        _patchCount++;
    }

    // KeYinCardItem.Spawn(Transform) does `s_PrefabPool.Spawn(parent).GetILRObject<KeYinCardItem>()`;
    // s_PrefabPool is null headless (its prefab-pool init is nopped) -> NRE that crash-aborted ~1361 keyin
    // rounds once keYinItems was populated. Rewrite Spawn to return a fresh KeYinCardItem stub (the visual
    // card object; the keyin gameplay effect is driven by KeYinCardFunctions off the card config, not this
    // instance) — same technique as the animator-pool spawn stub above.
    static void PatchKeYinCardItemSpawnModule(ModuleDefinition module)
    {
        var t = FindTypeM(module, "KeYinCardItem");
        if (t == null) { Console.WriteLine("  [native patch] WARN: KeYinCardItem not found (Spawn stub)"); return; }
        var spawn = t.Methods.FirstOrDefault(m => m.Name == "Spawn" && m.IsStatic);
        if (spawn == null || !spawn.HasBody) { Console.WriteLine("  [native patch] WARN: KeYinCardItem.Spawn not found"); return; }
        var il = spawn.Body.GetILProcessor();
        spawn.Body.Instructions.Clear(); spawn.Body.ExceptionHandlers.Clear(); spawn.Body.Variables.Clear();
        // newobj KeYinCardItem() TypeLoad-faults (its visual base ctor won't load in the patched module),
        // so allocate ctor-SKIPPED via RuntimeHelpers.GetUninitializedObject (same approach ReturnNonNullStub
        // uses for game types) — the returned instance is only held/visually-mutated, the keyin gameplay
        // runs off the card config in KeYinCardFunctions.
        var getTypeFromHandle = module.ImportReference(typeof(Type).GetMethod("GetTypeFromHandle", new[] { typeof(RuntimeTypeHandle) }));
        var getUninit = module.ImportReference(typeof(System.Runtime.CompilerServices.RuntimeHelpers)
            .GetMethod("GetUninitializedObject", new[] { typeof(Type) }));
        il.Append(il.Create(OpCodes.Ldtoken, t));
        il.Append(il.Create(OpCodes.Call, getTypeFromHandle));
        il.Append(il.Create(OpCodes.Call, getUninit));
        il.Append(il.Create(OpCodes.Castclass, t));
        il.Append(il.Create(OpCodes.Ret));
        _patchCount++;
    }

    // KeYinCardItem.InitData(int cardId, CardUseType useType) is the gameplay setup for a mid-battle-spawned
    // keyin card: it sets useType, cardInfo.id, sourceCardConfig, and **cardConfig** — the config that
    // Execute (IL_178C: currentKeYinCardItem.cardConfig.id) and KeYinCardFunctions.ExecuteAsync read off the
    // item. The real body's tail is all visual (LoadIcon/LoadSectBG/TMP labels) and TypeLoad-faults headless,
    // which is why KeYinCardItem was nopped wholesale — but that left cardConfig null -> the Sigil turn-1 NRE.
    // Rewrite InitData to ONLY the gameplay essentials, dropping the visual tail and the NetworkExtensions
    // .Clone<KeYinCardConfig> proto round-trip (it goes through the stubbed ProtobufParser and returns null —
    // same reason PatchCardItemUpgradeReloadModule drops Clone for regular cards): set cardConfig directly to
    // the FindCardConfig result. The configs are shared read-only dicts on this path, so no-clone is correct.
    static void PatchKeYinCardItemInitDataModule(ModuleDefinition module)
    {
        var t = FindTypeM(module, "KeYinCardItem");
        if (t == null) { Console.WriteLine("  [native patch] WARN: KeYinCardItem not found (InitData re-patch)"); return; }
        var m = t.Methods.FirstOrDefault(x => x.Name == "InitData" && x.Parameters.Count == 2
            && x.Parameters[0].ParameterType.FullName == "System.Int32"
            && x.Parameters[1].ParameterType.Name == "CardUseType");
        if (m == null || !m.HasBody) { Console.WriteLine("  [native patch] WARN: KeYinCardItem.InitData(int,CardUseType) not found"); return; }
        var setUseType = FindTypeM(module, "CardItemBase")?.Methods.FirstOrDefault(x => x.Name == "set_useType")
            ?? t.Methods.FirstOrDefault(x => x.Name == "set_useType");
        var getCardInfo = FindTypeM(module, "CardItemBase")?.Methods.FirstOrDefault(x => x.Name == "get_cardInfo");
        var cardInfoIdField = getCardInfo?.ReturnType.Resolve()?.Fields.FirstOrDefault(f => f.Name == "id");
        var findCardConfig = FindTypeM(module, "KeYinCardFactory")?.Methods.FirstOrDefault(x => x.Name == "FindCardConfig" && x.IsStatic && x.Parameters.Count == 1);
        // KeYinCardItem's OWN backing fields — set them via stfld DIRECTLY rather than the property setters,
        // because set_cardConfig/set_sourceCardConfig are nopped wholesale (KeYinCardItem visual methods) so
        // calling them would no-op. InitData is a KeYinCardItem method, so it can access its own privates.
        var sourceCfgField = t.Fields.FirstOrDefault(f => f.Name == "<sourceCardConfig>k__BackingField");
        var cardCfgField = t.Fields.FirstOrDefault(f => f.Name == "<cardConfig>k__BackingField");
        if (setUseType == null || getCardInfo == null || cardInfoIdField == null || findCardConfig == null
            || sourceCfgField == null || cardCfgField == null)
        { Console.WriteLine("  [native patch] WARN: KeYinCardItem.InitData re-patch members missing — skipped"); return; }
        var il = m.Body.GetILProcessor();
        m.Body.Instructions.Clear(); m.Body.ExceptionHandlers.Clear(); m.Body.Variables.Clear();
        // set_useType(useType)  (CardItemBase setter, not nopped)
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Ldarg_2));
        il.Append(il.Create(OpCodes.Call, setUseType));
        // cardInfo.id = cardId   (get_cardInfo is lazy-init'd by PatchLazyCardInfoModule so it's non-null)
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Call, getCardInfo));
        il.Append(il.Create(OpCodes.Ldarg_1));
        il.Append(il.Create(OpCodes.Stfld, module.ImportReference(cardInfoIdField)));
        // sourceCardConfig = FindCardConfig(cardId)   (direct field write — setter is nopped)
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Ldarg_1));
        il.Append(il.Create(OpCodes.Call, findCardConfig));
        il.Append(il.Create(OpCodes.Stfld, sourceCfgField));
        // cardConfig = sourceCardConfig   (no Clone — the proto round-trip stub returns null)
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Ldfld, sourceCfgField));
        il.Append(il.Create(OpCodes.Stfld, cardCfgField));
        il.Append(il.Create(OpCodes.Ret));
        _patchCount++;
    }

    // KeYinCardFunctions.swapKeYin (sigil 10165 "steal opponent's sigil") embeds its GAMEPLAY in DOTween
    // GENERIC cardConfig fix (default): instead of the bespoke swap/levelUp rewrites, make
    // KeYinItem.get_cardConfig read the LIVE model. Inject an __owner (BattleCharacter) field on KeYinItem
    // (set by the runner), and rewrite the getter to FindCardConfig(__owner.battleTempData.battleKeYinCards
    // [this.index]). Combined with callback-firing (so swapKeYin's OnComplete writes to battleKeYinCards land),
    // the ORIGINAL swapKeYin/levelUpKeYin run correctly -> the 4 bespoke KeYin patches delete. (When __owner is
    // null — not linked — it falls back to the original backing field, so the default path is unaffected.)
    // Debug helper: `int __keyinDbg(int id)` prints id to stderr and returns it (passthrough). Injected into the
    // redirect getter under ORACLE_KEYIN_DEBUG=1 to see exactly which sigil ids get_cardConfig reads.
    static MethodReference EnsureKeyinDbg(ModuleDefinition module)
    {
        var t = FindTypeM(module, "__OracleDbg");
        if (t == null) { t = new TypeDefinition("", "__OracleDbg", TypeAttributes.Public | TypeAttributes.Abstract | TypeAttributes.Sealed | TypeAttributes.Class, module.TypeSystem.Object); module.Types.Add(t); }
        var ex = t.Methods.FirstOrDefault(m => m.Name == "__keyinDbg");
        if (ex != null) return ex;
        var m = new MethodDefinition("__keyinDbg", MethodAttributes.Public | MethodAttributes.Static | MethodAttributes.HideBySig, module.TypeSystem.Int32);
        m.Parameters.Add(new ParameterDefinition("id", ParameterAttributes.None, module.TypeSystem.Int32));
        var getErr = module.ImportReference(typeof(Console).GetMethod("get_Error"));
        var wl = module.ImportReference(typeof(System.IO.TextWriter).GetMethod("WriteLine", new[] { typeof(int) }));
        var il = m.Body.GetILProcessor();
        il.Append(il.Create(OpCodes.Call, getErr));     // TextWriter
        il.Append(il.Create(OpCodes.Ldarg_0));          // id
        il.Append(il.Create(OpCodes.Callvirt, wl));     // Error.WriteLine(id)
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Ret));
        t.Methods.Add(m);
        return m;
    }

    internal static void PatchKeYinCardConfigRedirectModule(ModuleDefinition module)
    {
        var keYinItem = FindTypeM(module, "KeYinItem");
        var getCfg = keYinItem?.Methods.FirstOrDefault(m => m.Name == "get_cardConfig" && m.Parameters.Count == 0 && m.HasBody);
        var getIndex = keYinItem?.Methods.FirstOrDefault(m => m.Name == "get_index" && m.Parameters.Count == 0);
        var cfgBacking = keYinItem?.Fields.FirstOrDefault(f => f.Name.Contains("cardConfig"));
        var battleChar = FindTypeM(module, "BattleCharacter");
        var getTempData = battleChar?.Methods.FirstOrDefault(m => m.Name == "get_battleTempData");
        var keYinField = FindTypeM(module, "BattleTempData")?.Fields.FirstOrDefault(f => f.Name == "battleKeYinCards");
        var findCfg = FindTypeM(module, "KeYinCardFactory")?.Methods.FirstOrDefault(m => m.Name == "FindCardConfig" && m.IsStatic && m.Parameters.Count == 1);
        if (keYinItem == null || getCfg == null || getIndex == null || cfgBacking == null || battleChar == null
            || getTempData == null || keYinField == null || findCfg == null)
        { Console.WriteLine($"  [native patch] WARN: keyin-redirect members missing (item={keYinItem!=null} get={getCfg!=null} idx={getIndex!=null} bk={cfgBacking!=null} td={getTempData!=null} fld={keYinField!=null} find={findCfg!=null})"); return; }

        var ownerField = keYinItem.Fields.FirstOrDefault(f => f.Name == "__owner");
        if (ownerField == null) { ownerField = new FieldDefinition("__owner", FieldAttributes.Public, module.ImportReference(battleChar)); keYinItem.Fields.Add(ownerField); }

        var listType = keYinField.FieldType;            // List<int>
        var getItemDef = listType.Resolve()?.Methods.FirstOrDefault(m => m.Name == "get_Item" && m.Parameters.Count == 1);
        if (getItemDef == null) { Console.WriteLine("  [native patch] WARN: keyin-redirect: List get_Item missing"); return; }
        var getItem = new MethodReference(getItemDef.Name, getItemDef.ReturnType, listType) { HasThis = getItemDef.HasThis, ExplicitThis = getItemDef.ExplicitThis, CallingConvention = getItemDef.CallingConvention };
        foreach (var p in getItemDef.Parameters) getItem.Parameters.Add(new ParameterDefinition(p.ParameterType));

        var getTD = module.ImportReference(getTempData); var fld = module.ImportReference(keYinField);
        var find = module.ImportReference(findCfg); var gIdx = module.ImportReference(getIndex);
        var body = getCfg.Body; body.Instructions.Clear(); body.ExceptionHandlers.Clear(); body.Variables.Clear();
        var il = body.GetILProcessor();
        var redir = il.Create(OpCodes.Ldarg_0);
        // if (this.__owner == null) return this.<cardConfig>backing;
        il.Append(il.Create(OpCodes.Ldarg_0)); il.Append(il.Create(OpCodes.Ldfld, ownerField)); il.Append(il.Create(OpCodes.Brtrue, redir));
        il.Append(il.Create(OpCodes.Ldarg_0)); il.Append(il.Create(OpCodes.Ldfld, module.ImportReference(cfgBacking))); il.Append(il.Create(OpCodes.Ret));
        // return FindCardConfig(this.__owner.battleTempData.battleKeYinCards[this.index]);
        il.Append(redir);                                       // ldarg.0 (this)
        il.Append(il.Create(OpCodes.Ldfld, ownerField));        // __owner
        il.Append(il.Create(OpCodes.Callvirt, getTD));          // battleTempData
        il.Append(il.Create(OpCodes.Ldfld, fld));               // battleKeYinCards
        il.Append(il.Create(OpCodes.Ldarg_0)); il.Append(il.Create(OpCodes.Callvirt, gIdx));   // this.index
        il.Append(il.Create(OpCodes.Callvirt, getItem));        // [index] -> int sigil id
        if (Environment.GetEnvironmentVariable("ORACLE_KEYIN_DEBUG") == "1")
            il.Append(il.Create(OpCodes.Call, EnsureKeyinDbg(module)));   // id -> id (prints id to stderr)
        // EMPTY SLOT (id == 0): an unused sigil slot has NO config (null), but FindCardConfig(0) returns a real
        // config[0] -> spurious sigil effect. Return null for id==0 to match the empty-slot semantics.
        var lnull = il.Create(OpCodes.Pop);
        il.Append(il.Create(OpCodes.Dup)); il.Append(il.Create(OpCodes.Brfalse, lnull));
        il.Append(il.Create(OpCodes.Call, find));               // FindCardConfig(id) -> KeYinCardConfig
        il.Append(il.Create(OpCodes.Ret));
        il.Append(lnull); il.Append(il.Create(OpCodes.Ldnull)); il.Append(il.Create(OpCodes.Ret));   // id==0 -> null
        _patchCount++;
        Console.WriteLine("  [native patch] KeYinItem.get_cardConfig -> live battleKeYinCards[index] redirect (+__owner field); generic cardConfig fix");
    }


    // BattleCharacterUI.set_tempLife — rewrite to JUST store the gameplay backing field m_TempLife (eliding
    // the visual m_LifeLabel.SetActive / DOScale / label.text). The real setter NREs on the null m_LifeLabel
    // before reaching the store, so nopping it (the old behavior) dropped every `characterUI.tempLife += delta`
    // from ModifyTempLife -> the life-resource shield never updated headless. This makes the gameplay write
    // land while the visual stays inert.
    // Stale-mirror detector: add a sentinel offset to every int VISUAL-MIRROR getter's return value, so a
    // normal-vs-perturbed corpus diff flags any round whose combat result moves => it READ that mirror for
    // gameplay (gap-#2). Requires no mirror->model map. hp/def/anima/maxHp should NOT move (combat reads the
    // model); tempLife/exp SHOULD (combat reads the mirror) — which empirically validates the static map.
    static void PatchPerturbMirrorsModule(ModuleDefinition module)
    {
        // GENERALIZED: a "visual mirror" is any parameterless int getter on a UI type (ILRComponentBase-derived
        // MonoBehaviour). Perturb EVERY one across the whole game — not a hand list — so the detector surfaces any
        // mirror dependency, including ones never enumerated. A getter that just `ret`s a field is a mirror
        // candidate; we offset its return by +0x4000. Guards: skip getters with branches/calls (computed values,
        // not flat mirrors) so we only perturb the pure read-a-field accessors gameplay could mistake for truth.
        int n = 0, types = 0;
        foreach (var ui in AllModuleTypes(module))
        {
            if (!DerivesFrom(ui, "ILRComponentBase")) continue;
            types++;
            foreach (var g in ui.Methods.Where(m => m.Name.StartsWith("get_") && m.Parameters.Count == 0
                                                    && m.HasBody && m.ReturnType.MetadataType == MetadataType.Int32))
            {
                // only flat field mirrors: a body of ldarg.0/ldfld/ret (no calls/branches => not a computed value)
                if (g.Body.Instructions.Any(i => i.OpCode.FlowControl == FlowControl.Call
                                                 || i.OpCode.FlowControl == FlowControl.Cond_Branch
                                                 || i.OpCode.FlowControl == FlowControl.Branch)) continue;
                var il = g.Body.GetILProcessor();
                foreach (var ret in g.Body.Instructions.Where(i => i.OpCode == OpCodes.Ret).ToList())
                {
                    il.InsertBefore(ret, il.Create(OpCodes.Ldc_I4, 0x4000));   // value + 16384 (clearly wrong if used)
                    il.InsertBefore(ret, il.Create(OpCodes.Add));
                }
                n++;
            }
        }
        // OBJECT mirrors (env ORACLE_PERTURB_MIRRORS_OBJ=1): perturb the cardConfig getter on the KeYin mirror
        // types to return a WRONG-BUT-VALID config (a fresh empty CardConfig, id=0) — NOT null. Null crashes the
        // render/setup path (any non-null check / field deref NREs), which floods the diff with crash-aborts
        // instead of real reads (validated: null -> 1510 crash-aborted rounds on the HD corpus). A wrong-but-valid
        // object is the object-analogue of the int +0x4000 offset: rendering survives (object is non-null), but any
        // gameplay that READS a field off it (cardConfig.id, the swapKeYin/levelUpKeYin surface) gets a wrong value
        // and the round MOVES. So a moved round = a real gameplay read, with no crash false-positives.
        if (Environment.GetEnvironmentVariable("ORACLE_PERTURB_MIRRORS_OBJ") == "1")
        {
            var cardCfg = FindTypeM(module, "CardConfig");
            var ctor = cardCfg?.Methods.FirstOrDefault(m => m.IsConstructor && !m.IsStatic && m.Parameters.Count == 0);
            if (ctor == null) { Console.WriteLine("  [native patch] WARN: perturb-obj: CardConfig() ctor not found"); }
            else foreach (var tn in new[] { "KeYinItem", "KeYinCardItem" })
            {
                var t = FindTypeM(module, tn);
                var g = t?.Methods.FirstOrDefault(m => m.Name == "get_cardConfig" && m.Parameters.Count == 0 && m.HasBody);
                if (g == null) continue;
                g.Body.ExceptionHandlers.Clear(); g.Body.Variables.Clear();
                var il = g.Body.GetILProcessor();
                g.Body.Instructions.Clear();
                il.Append(il.Create(OpCodes.Newobj, g.Module.ImportReference(ctor)));   // wrong-but-valid (id=0), no NRE
                il.Append(il.Create(OpCodes.Ret));
                n++;
            }
        }
        Console.WriteLine($"  [native patch] PERTURB MIRRORS: perturbed {n} int mirror getters across {types} UI types (detector mode)");
    }

    // Walk the BaseType chain by simple name (within-module resolution) — true if `t` derives from `baseName`.
    static bool DerivesFrom(TypeDefinition t, string baseName)
    {
        var cur = t.BaseType;
        int guard = 0;
        while (cur != null && guard++ < 32)
        {
            if (cur.Name == baseName) return true;
            cur = cur.Resolve()?.BaseType;
        }
        return false;
    }



    // DIAGNOSTIC (opt-in via env ORACLE_DEBUG_XS=1; inert otherwise): prepend a print to
    // CardActionBase.ExecuteEffect logging the executing card's (gridNumber, cardConfig.id) every call.
    // This is how the card-7000067 (五行流转) infinite self-recursion was diagnosed — the trace showed
    // `grid=3 id=7000067` repeating forever (the self-transform was a no-op because CardItem.InitData was
    // nopped). Kept as a reusable probe for the next combo/recursion divergence. Purely observational.
    static void PatchDebugExecuteEffectModule(ModuleDefinition module)
    {
        var cab = FindTypeM(module, "CardActionBase");
        var ee = cab?.Methods.FirstOrDefault(m => m.Name == "ExecuteEffect" && m.HasBody);
        var getCardItem = cab?.Methods.FirstOrDefault(m => m.Name == "get_cardItem");
        var getCardConfig = cab?.Methods.FirstOrDefault(m => m.Name == "get_cardConfig");
        var ciType = FindTypeM(module, "CardItem");
        var gridField = ciType?.Fields.FirstOrDefault(f => f.Name == "gridNumber")
            ?? FindTypeM(module, "CardItemBase")?.Fields.FirstOrDefault(f => f.Name == "gridNumber");
        var cfgIdField = getCardConfig?.ReturnType.Resolve()?.Fields.FirstOrDefault(f => f.Name == "id");
        if (ee == null || getCardItem == null || getCardConfig == null || gridField == null || cfgIdField == null)
        { Console.WriteLine("  [native patch] WARN: debug-XS members missing — skipped"); return; }
        var wrStr = module.ImportReference(typeof(Console).GetMethod("Write", new[] { typeof(string) }));
        var wrInt = module.ImportReference(typeof(Console).GetMethod("Write", new[] { typeof(int) }));
        var wrLine = module.ImportReference(typeof(Console).GetMethod("WriteLine", new[] { typeof(int) }));
        var il = ee.Body.GetILProcessor();
        var first = ee.Body.Instructions[0];
        void Ins(Instruction i) => il.InsertBefore(first, i);
        Ins(il.Create(OpCodes.Ldstr, "XS-EXEC grid="));
        Ins(il.Create(OpCodes.Call, wrStr));
        Ins(il.Create(OpCodes.Ldarg_0));
        Ins(il.Create(OpCodes.Call, getCardItem));
        Ins(il.Create(OpCodes.Ldfld, gridField));
        Ins(il.Create(OpCodes.Call, wrInt));
        Ins(il.Create(OpCodes.Ldstr, " id="));
        Ins(il.Create(OpCodes.Call, wrStr));
        Ins(il.Create(OpCodes.Ldarg_0));
        Ins(il.Create(OpCodes.Call, getCardConfig));
        Ins(il.Create(OpCodes.Ldfld, module.ImportReference(cfgIdField)));
        Ins(il.Create(OpCodes.Call, wrLine));
        _patchCount++;
    }

    // CardItemBase.get_cardInfo() is an auto-property getter that just returns <cardInfo>k__BackingField.
    // For a ctor-skipped item (the KeYinCardItem.Spawn stub allocates via GetUninitializedObject, so the
    // ctor that `new`s the CardInfo never runs) that field is null, and InitData's `cardInfo.id = cardId`
    // NREs. The derived InitData canNOT seed the base PRIVATE backing field (CoreCLR throws
    // FieldAccessException), but the getter itself has access — so make it LAZY-init: return a fresh CardInfo
    // when the field is null. Harmless for real card items (field already set; lazy branch never taken).
    static void PatchLazyCardInfoModule(ModuleDefinition module)
    {
        var bt = FindTypeM(module, "CardItemBase");
        var getter = bt?.Methods.FirstOrDefault(x => x.Name == "get_cardInfo" && x.HasBody);
        if (getter == null) { Console.WriteLine("  [native patch] WARN: CardItemBase.get_cardInfo not found (lazy-init)"); return; }
        var backing = bt!.Fields.FirstOrDefault(f => f.Name == "<cardInfo>k__BackingField");
        var cardInfoType = getter.ReturnType.Resolve();
        var ctor = cardInfoType?.Methods.FirstOrDefault(x => x.IsConstructor && !x.IsStatic && x.Parameters.Count == 0);
        if (backing == null || ctor == null) { Console.WriteLine("  [native patch] WARN: get_cardInfo lazy-init members missing — skipped"); return; }
        var il = getter.Body.GetILProcessor();
        getter.Body.Instructions.Clear(); getter.Body.ExceptionHandlers.Clear(); getter.Body.Variables.Clear();
        var ret = il.Create(OpCodes.Ldarg_0);          // L_ret: reload + return the (now non-null) field
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Ldfld, backing));
        il.Append(il.Create(OpCodes.Brtrue_S, ret));
        il.Append(il.Create(OpCodes.Ldarg_0));
        il.Append(il.Create(OpCodes.Newobj, module.ImportReference(ctor)));
        il.Append(il.Create(OpCodes.Stfld, backing));
        il.Append(ret);
        il.Append(il.Create(OpCodes.Ldfld, backing));
        il.Append(il.Create(OpCodes.Ret));
        _patchCount++;
    }

    /// <summary>
    /// DEPRECATED: Pre-load patching doesn't work because Cecil can't resolve all types.
    /// Use PatchLoadedAssembly() instead.
    /// </summary>
    public static MemoryStream Patch(byte[] dllBytes, byte[]? pdbBytes = null)
    {
        _patchCount = 0;

        using var dllStream = new MemoryStream(dllBytes);
        using var pdbStream = pdbBytes != null ? new MemoryStream(pdbBytes) : null;

        // Register facade directory so Cecil can resolve assembly references when writing
        var resolver = new DefaultAssemblyResolver();
        var facadesDir = Path.Combine(
            Path.GetDirectoryName(typeof(DllPatcher).Assembly.Location) ?? "",
            "..", "..", "..", "..", "UnityStubs", "bin", "facades");
        if (Directory.Exists(facadesDir))
            resolver.AddSearchDirectory(facadesDir);

        var readerParams = new ReaderParameters
        {
            ReadWrite = false,
            InMemory = true,
            AssemblyResolver = resolver,
            ReadSymbols = false, // Skip PDB — we only need IL bytecode
        };

        // Use a resolver that never fails — returns a dummy assembly for unknown references
        resolver.ResolveFailure += (sender, reference) =>
        {
            // Create a minimal dummy assembly so Cecil doesn't crash
            var dummy = AssemblyDefinition.CreateAssembly(
                new AssemblyNameDefinition(reference.Name, reference.Version ?? new Version(0, 0)),
                reference.Name, ModuleKind.Dll);
            return dummy;
        };

        var module = ModuleDefinition.ReadModule(dllStream, readerParams);

        // Apply patches
        PatchBattleCharacterUI(module);
        PatchTmpFloatingText(module);
        PatchHpBarTweenEffect(module);
        PatchHpBarCalibrationEffect(module);
        PatchDefItem(module);
        PatchAnimaItem(module);
        PatchKeYinItem(module);

        Console.WriteLine($"  Cecil patches applied: {_patchCount}");

        // Write patched module to memory (skip symbol writing, don't resolve types)
        var output = new MemoryStream();
        var writerParams = new WriterParameters
        {
            WriteSymbols = false,
        };
        module.Write(output, writerParams);
        output.Position = 0;
        return output;
    }

    /// <summary>
    /// Replace a method body with just 'ret' (void) or 'ldarg.0; ret' (return this).
    /// </summary>
    internal static void NopMethod(MethodDefinition method)
    {
        if (method == null || !method.HasBody) return;
        var il = method.Body.GetILProcessor();
        method.Body.Instructions.Clear();
        method.Body.ExceptionHandlers.Clear();
        method.Body.Variables.Clear();

        if (method.ReturnType.FullName == "System.Void")
        {
            il.Append(il.Create(OpCodes.Ret));
        }
        else if (method.ReturnType == method.DeclaringType)
        {
            // Return 'this' for fluent methods
            il.Append(il.Create(OpCodes.Ldarg_0));
            il.Append(il.Create(OpCodes.Ret));
        }
        else if (method.ReturnType.IsValueType)
        {
            // Return default(T) for value types
            var local = new VariableDefinition(method.ReturnType);
            method.Body.Variables.Add(local);
            il.Append(il.Create(OpCodes.Ldloca_S, local));
            il.Append(il.Create(OpCodes.Initobj, method.ReturnType));
            il.Append(il.Create(OpCodes.Ldloc_0));
            il.Append(il.Create(OpCodes.Ret));
        }
        else
        {
            // Return null for reference types
            il.Append(il.Create(OpCodes.Ldnull));
            il.Append(il.Create(OpCodes.Ret));
        }

        _patchCount++;
    }

    /// <summary>
    /// Replace a property setter with just storing to the backing field.
    /// setter(value) → this.m_Field = value; return;
    /// </summary>
    static void StripSetter(TypeDefinition type, string propertyName, string backingFieldName)
    {
        var prop = type.Properties.FirstOrDefault(p => p.Name == propertyName);
        if (prop?.SetMethod == null) return;

        var field = type.Fields.FirstOrDefault(f => f.Name == backingFieldName);
        if (field == null) return;

        var setter = prop.SetMethod;
        var il = setter.Body.GetILProcessor();
        setter.Body.Instructions.Clear();
        setter.Body.ExceptionHandlers.Clear();
        setter.Body.Variables.Clear();

        // this.field = value; return;
        il.Append(il.Create(OpCodes.Ldarg_0));  // this
        il.Append(il.Create(OpCodes.Ldarg_1));  // value
        il.Append(il.Create(OpCodes.Stfld, field));
        il.Append(il.Create(OpCodes.Ret));

        _patchCount++;
    }

    // ── Per-class patches ──

    static void PatchBattleCharacterUI(ModuleDefinition module)
    {
        var type = module.Types.FirstOrDefault(t => t.Name == "BattleCharacterUI");
        if (type == null) { Console.WriteLine("  WARN: BattleCharacterUI not found"); return; }

        // Strip property setters to state-only (remove UI text/animation updates)
        StripSetter(type, "hp", "m_Hp");
        StripSetter(type, "maxHp", "m_MaxHp");
        StripSetter(type, "def", "m_Def");
        StripSetter(type, "anima", "m_Anima");
        StripSetter(type, "tempLife", "m_TempLife");

        // Nop visual-only methods
        foreach (var name in new[] { "SetTipoUI", "RefreshBuff", "RefreshAllBuff",
            "UpdateStatusBarPos", "ShowDamageEffect", "ShowHealEffect",
            "PlayHurtAnimation", "RefreshCardScroll", "UpdateCardUI",
            "PrepareILRComponent", "InitData" })
        {
            var methods = type.Methods.Where(m => m.Name == name);
            foreach (var m in methods) NopMethod(m);
        }
    }

    // Not used in post-load patching
    static void PatchTmpFloatingText(ModuleDefinition module) { }

    static void PatchHpBarTweenEffect(ModuleDefinition module)
    {
        var type = module.Types.FirstOrDefault(t => t.Name == "HpBarTweenEffect");
        if (type == null) return;
        foreach (var method in type.Methods)
        {
            if (method.IsConstructor) continue;
            NopMethod(method);
        }
    }

    static void PatchHpBarCalibrationEffect(ModuleDefinition module)
    {
        var type = module.Types.FirstOrDefault(t => t.Name == "HpBarCalibrationEffect");
        if (type == null) return;
        foreach (var method in type.Methods)
        {
            if (method.IsConstructor) continue;
            NopMethod(method);
        }
    }

    static void PatchDefItem(ModuleDefinition module)
    {
        var type = module.Types.FirstOrDefault(t => t.Name == "DefItem");
        if (type == null) return;
        foreach (var method in type.Methods)
        {
            if (method.IsConstructor) continue;
            NopMethod(method);
        }
    }

    static void PatchAnimaItem(ModuleDefinition module)
    {
        var type = module.Types.FirstOrDefault(t => t.Name == "AnimaItem");
        if (type == null) return;
        foreach (var method in type.Methods)
        {
            if (method.IsConstructor) continue;
            NopMethod(method);
        }
    }

    static void PatchKeYinItem(ModuleDefinition module)
    {
        var type = module.Types.FirstOrDefault(t => t.Name == "KeYinItem");
        if (type == null) return;
        foreach (var method in type.Methods)
        {
            if (method.IsConstructor) continue;
            NopMethod(method);
        }
    }

    // OpenTongXiuHouShouBuChang (the ONLY combat-math feature flag IsOpen gates — canRevive heal-from-
    // death in BattleCharacter.ModifyHp) — OpenType enum value 74 (Proto/OpenType.cs:62).
    const int OpenTongXiuHouShouBuChang = 74;

    static void PatchOpenManagerIsOpenModule(ModuleDefinition module)
    {
        var omType = FindTypeM(module, "OpenManager");
        if (omType == null) { Console.WriteLine("  [native patch] WARN: OpenManager not found — IsOpen patch skipped"); return; }
        var isOpen = omType.Methods.FirstOrDefault(m =>
            m.Name == "IsOpen" && m.Parameters.Count == 2
            && m.ReturnType.FullName == "System.Boolean");
        if (isOpen == null || !isOpen.HasBody) { Console.WriteLine("  [native patch] WARN: OpenManager.IsOpen(OpenType,int[]) not found — patch skipped"); return; }
        var il = isOpen.Body.GetILProcessor();
        isOpen.Body.Instructions.Clear(); isOpen.Body.ExceptionHandlers.Clear(); isOpen.Body.Variables.Clear();
        il.Append(il.Create(OpCodes.Ldarg_0));                         // type (int32 on stack)
        il.Append(il.Create(OpCodes.Ldc_I4, OpenTongXiuHouShouBuChang)); // 74
        il.Append(il.Create(OpCodes.Ceq));                            // type == 74
        il.Append(il.Create(OpCodes.Ret));
        _patchCount++;
        Console.WriteLine("  [native patch] Patched OpenManager.IsOpen(OpenType,int[]) -> type == OpenTongXiuHouShouBuChang");
    }
}
