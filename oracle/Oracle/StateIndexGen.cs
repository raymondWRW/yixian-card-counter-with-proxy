// StateIndexGen — the "gameplay state index" generator (the general solution to the inert-visual bug class).
//
// PRINCIPLE: headless combat = the game's own action code running with rendering neutralized. The ONLY thing
// that can make a card/sigil/fate produce a wrong result headless is when its code READS a gameplay value off a
// VISUAL MIRROR object (a UI MonoBehaviour / ILRComponentBase) instead of the canonical model — because the
// mirror is stale/empty headless. That set of reads is FINITE and statically enumerable.
//
// So instead of discovering each one reactively via a parity failure (whack-a-mole), this walks EVERY effect
// entry point (every CardActionBase.ExecuteEffect, every KeYinCardFunctions/FateStrategyFunctions method),
// transitively follows the callgraph, and records every field/property READ whose DECLARING type is a visual/UI
// type but whose MEMBER value type is gameplay DATA (int / *Config / Proto.* — NOT itself visual). That union is
// the closed "core state we must emulate" — the exact, complete surface the headless runner has to make correct.
//
//   dotnet Oracle.dll --gen-state-index [--out <path>]   ->  data/game/oracle_audit/state_index.json
//
// Cross-check: the differential perturbation detector (scripts/detect_mirror_dependencies.py) is the DYNAMIC
// completeness backstop — if perturbing all mirrors moves only rounds whose cards are in this index, the index
// is provably exhaustive; if something else moves, a transitive/virtual read was missed and the index extends.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using ILRuntime.Mono.Cecil;
using ILRuntime.Mono.Cecil.Cil;

namespace YiXianOracle;

internal static class StateIndexGen
{
    static readonly string[] VisualNs = { "UnityEngine", "TMPro", "Spine", "DG.Tweening", "Cinemachine" };
    static readonly string[] UiBases = { "ILRComponentBase", "ILRPanelBase" };

    static Dictionary<string, TypeDefinition> _byName = new();
    static HashSet<string> _mirrorTypes = new();   // game UI VIEW types that hold gameplay mirrors (no model)

    // External rendering type (namespace-based — no resolution needed).
    static bool IsVisualType(TypeReference? t)
    {
        if (t == null || t.IsValueType || t.IsGenericParameter) return false;
        var ns = t.Namespace ?? "";
        return VisualNs.Any(v => ns == v || ns.StartsWith(v + "."));
    }

    // Resolve a TypeReference to its in-module TypeDefinition via our own name map (Cecil's Resolve() is flaky
    // on the in-memory module — in-module base chains return null and break inheritance walks).
    static TypeDefinition? Def(TypeReference? t) => t != null && _byName.TryGetValue(t.FullName, out var d) ? d : null;

    static bool DerivesFromName(TypeReference? t, params string[] baseNames)
    {
        for (var cur = Def(t); cur != null; cur = Def(cur.BaseType))
            if (baseNames.Contains(cur.BaseType?.Name) || baseNames.Contains(cur.Name)) return true;
        return false;
    }

    // A type OWNS the canonical model if it (or a base) has a field of a Proto.* type (BattleCharacter holds
    // battleTempData). Model-owners are the gameplay ENTITY, NOT a mirror — even though they're ILRComponentBase.
    static bool OwnsProtoModel(TypeDefinition? t)
    {
        for (; t != null; t = Def(t.BaseType))
            if (t.Fields.Any(f => (f.FieldType.Namespace ?? "").StartsWith("Proto"))) return true;
        return false;
    }

    // A UI MIRROR/VIEW type = a game class deriving from a UI base (ILRComponentBase/ILRPanelBase) that does NOT
    // own a Proto model. Its fields are primitives/configs SYNCED from the model and stale headless — the bug
    // class. (BattleCharacterUI/KeYinItem/AnimaItem/CardItem yes; BattleCharacter no — it owns battleTempData.)
    static bool IsUiMirrorType(TypeReference? t) =>
        t != null && _mirrorTypes.Contains(t.FullName);

    // A read worth recording = a LEAF gameplay value (int/bool/*Config/Proto data) off a mirror — NOT a
    // navigation hop to another component/view (.characterUI, .animator) nor a pure-visual member (.transform).
    static bool IsGameplayLeaf(TypeReference? t) =>
        t != null && !IsVisualType(t) && !DerivesFromName(t, UiBases);

    record struct Read(string Member, string MemberType);

    public static void Generate(string dllPath, string outPath)
    {
        var rp = new ReaderParameters { ReadWrite = false, InMemory = true, ReadSymbols = false };
        var asmResolver = new DefaultAssemblyResolver();
        asmResolver.AddSearchDirectory(Path.GetDirectoryName(dllPath));
        rp.AssemblyResolver = asmResolver;
        var module = ModuleDefinition.ReadModule(new MemoryStream(File.ReadAllBytes(dllPath)), rp);

        var allTypes = AllTypes(module).ToList();
        _byName = new Dictionary<string, TypeDefinition>();
        foreach (var t in allTypes) _byName[t.FullName] = t;

        // ── entry points: every effect method combat dispatches to ──
        var entries = new List<MethodDefinition>();
        var entrySeen = new HashSet<string>();
        void AddEntry(MethodDefinition m) { if (m.HasBody && !m.IsConstructor && entrySeen.Add(m.FullName)) entries.Add(m); }
        // card effects: every CardActionBase subclass' override (OnExecuted is the per-card effect; ExecuteEffect
        // the base dispatcher). Both are async kickoffs — the callgraph walk follows them into MoveNext.
        foreach (var t in allTypes)
            if (DerivesFromName(t, "CardActionBase"))
                foreach (var m in t.Methods.Where(m => (m.Name == "OnExecuted" || m.Name == "ExecuteEffect") && m.HasBody))
                    AddEntry(m);
        // sigils + fates: dedicated effect-dispatcher classes
        foreach (var tn in new[] { "KeYinCardFunctions", "FateStrategyFunctions" })
        {
            var t = allTypes.FirstOrDefault(x => x.Name == tn);
            if (t != null) foreach (var m in t.Methods) AddEntry(m);
        }

        // The model ENTITY = the UI-derived type combat passes as the actor (src/dst of every effect). Combat
        // reads the canonical model OFF it (battleTempData) — that's correct, NOT a stale mirror. Derive it from
        // the EFFECT signatures ONLY (cards/sigils/fates, which take BattleCharacter src/dst) — BEFORE adding the
        // BattleExecuter/seasonal entries whose params (panels, etc.) would wrongly exclude real mirror types.
        var actorTypes = new HashSet<string>(entries
            .SelectMany(e => e.Parameters.Select(p => p.ParameterType))
            .Where(pt => DerivesFromName(pt, UiBases))
            .Select(pt => pt.FullName));

        // SEASONAL MECHANICS (Dream/Mirage/QiYun/...) have NO dedicated class — they're woven into the COMBAT turn
        // loop behind `SeasonMecCanUse(SeasonMechanismType.X)` gates. Root at BattleExecuter.Execute (the combat
        // driver): its transitive callgraph reaches the IN-COMBAT seasonal branches WITHOUT pulling in prep-phase
        // panels (relic vote / keyin mall / fate-select UI), which are never reached during a battle. A
        // SeasonMecCanUse branch that matters for combat damage is, by definition, reachable from Execute.
        var be = allTypes.FirstOrDefault(x => x.Name == "BattleExecuter");
        if (be != null) foreach (var m in be.Methods.Where(m => m.Name.StartsWith("Execute"))) AddEntry(m);
        _mirrorTypes = new HashSet<string>(
            allTypes.Where(t => DerivesFromName(t, UiBases) && !actorTypes.Contains(t.FullName)).Select(t => t.FullName));

        // ── 1. single pass: per method, its DIRECT mirror-reads + the GAME methods it calls (the callgraph) ──
        var direct = new Dictionary<MethodDefinition, List<Read>>();
        var callees = new Dictionary<MethodDefinition, List<MethodDefinition>>();
        foreach (var t in allTypes)
            foreach (var m in t.Methods)
            {
                if (!m.HasBody) continue;
                var reads = new List<Read>();
                var cs = new List<MethodDefinition>();
                foreach (var ins in m.Body.Instructions)
                {
                    // field read: ldfld/ldsfld
                    if ((ins.OpCode == OpCodes.Ldfld || ins.OpCode == OpCodes.Ldsfld) && ins.Operand is FieldReference fr)
                    {
                        if (IsUiMirrorType(fr.DeclaringType) && IsGameplayLeaf(fr.FieldType))
                            reads.Add(new Read($"{fr.DeclaringType.Name}.{fr.Name}", fr.FieldType.Name));
                    }
                    // property read: call/callvirt to a parameterless get_*; also a callgraph edge.
                    else if ((ins.OpCode == OpCodes.Call || ins.OpCode == OpCodes.Callvirt || ins.OpCode == OpCodes.Newobj)
                             && ins.Operand is MethodReference mref)
                    {
                        if (mref.Name.StartsWith("get_") && mref.Parameters.Count == 0
                            && IsUiMirrorType(mref.DeclaringType) && IsGameplayLeaf(mref.ReturnType))
                            reads.Add(new Read($"{mref.DeclaringType.Name}.{mref.Name}", mref.ReturnType.Name));
                        // callgraph edge to a GAME method (resolve via our name map — Cecil Resolve() is flaky here)
                        var dt = Def(mref.DeclaringType);
                        var callee = dt?.Methods.FirstOrDefault(x => x.Name == mref.Name && x.Parameters.Count == mref.Parameters.Count && x.HasBody);
                        if (callee != null && !IsVisualType(callee.DeclaringType)) cs.Add(callee);
                    }
                }
                // ASYNC: effect methods are `async UniTask` — the real reads live in the compiler-generated
                // <Name>d__N.MoveNext state machine, NOT the kickoff body. Follow [AsyncStateMachine(typeof(SM))].
                var sm = m.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name == "AsyncStateMachineAttribute");
                if (sm != null && sm.ConstructorArguments.Count > 0 && sm.ConstructorArguments[0].Value is TypeReference smRef)
                {
                    var smDef = Def(smRef);
                    if (smDef != null)
                        foreach (var mv in smDef.Methods.Where(x => x.Name == "MoveNext" && x.HasBody))
                            cs.Add(mv);
                }
                if (reads.Count > 0) direct[m] = reads;
                if (cs.Count > 0) callees[m] = cs;
            }

        // ── 3. per entry: DFS the callgraph, union the direct mirror-reads ──
        var perEntry = new Dictionary<string, SortedSet<string>>();
        var surface = new Dictionary<string, (int count, SortedSet<string> ex)>();
        foreach (var entry in entries)
        {
            var seen = new HashSet<MethodDefinition>();
            var stack = new Stack<MethodDefinition>();
            stack.Push(entry);
            var hits = new SortedSet<string>();
            while (stack.Count > 0)
            {
                var m = stack.Pop();
                if (!seen.Add(m) || seen.Count > 4000) continue;
                if (direct.TryGetValue(m, out var rs))
                    foreach (var r in rs) hits.Add($"{r.Member}:{r.MemberType}");
                if (callees.TryGetValue(m, out var cs))
                    foreach (var c in cs) if (!seen.Contains(c)) stack.Push(c);
            }
            if (hits.Count == 0) continue;
            var key = $"{entry.DeclaringType.Name}.{entry.Name}";
            perEntry[key] = hits;
            foreach (var h in hits)
            {
                if (!surface.TryGetValue(h, out var v)) v = (0, new SortedSet<string>());
                v.count++;
                if (v.ex.Count < 8) v.ex.Add(key);
                surface[h] = v;
            }
        }

        // ── 4. emit ──
        var outObj = new
        {
            generated = DateTime.UtcNow.ToString("o"),
            dll = Path.GetFileName(dllPath),
            entry_points_scanned = entries.Count,
            entry_points_with_mirror_reads = perEntry.Count,
            distinct_mirror_members = surface.Count,
            surface = surface.OrderByDescending(kv => kv.Value.count)
                             .ToDictionary(kv => kv.Key, kv => new { count = kv.Value.count, examples = kv.Value.ex.ToList() }),
            entry_points = perEntry.OrderBy(kv => kv.Key).ToDictionary(kv => kv.Key, kv => kv.Value.ToList()),
        };
        Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
        File.WriteAllText(outPath, JsonSerializer.Serialize(outObj, new JsonSerializerOptions { WriteIndented = true }));

        Console.WriteLine($"=== gameplay state index -> {outPath} ===");
        Console.WriteLine($"  entry points scanned: {entries.Count}  ({entries.Count(e => e.DeclaringType.Name == "KeYinCardFunctions" || e.DeclaringType.Name == "FateStrategyFunctions")} sigil/fate, rest card effects)");
        Console.WriteLine($"  entry points that read a VISUAL MIRROR for gameplay: {perEntry.Count}");
        Console.WriteLine($"  distinct visual-mirror members read (THE closed surface to emulate): {surface.Count}");
        foreach (var kv in surface.OrderByDescending(kv => kv.Value.count).Take(25))
            Console.WriteLine($"    {kv.Value.count,5}x  {kv.Key}");
    }

    static IEnumerable<TypeDefinition> AllTypes(ModuleDefinition m)
    {
        foreach (var t in m.Types) { yield return t; foreach (var n in Nested(t)) yield return n; }
    }
    static IEnumerable<TypeDefinition> Nested(TypeDefinition t)
    {
        foreach (var n in t.NestedTypes) { yield return n; foreach (var nn in Nested(n)) yield return nn; }
    }
    static bool CallsNamed(MethodDefinition m, string calleeName)
    {
        foreach (var ins in m.Body.Instructions)
            if ((ins.OpCode == OpCodes.Call || ins.OpCode == OpCodes.Callvirt)
                && ins.Operand is MethodReference mr && mr.Name == calleeName)
                return true;
        return false;
    }
}
