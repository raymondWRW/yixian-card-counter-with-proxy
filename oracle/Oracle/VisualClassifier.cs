// VisualClassifier — READ the code (don't run it) to decide, for every method, whether it is PURE-VISUAL (safe
// to neutralize headless) or GAMEPLAY (must run). The no-op layer is dangerous precisely because a blind nop can
// drop a method that ALSO mutates gameplay. So instead of nop-by-hand-then-find-the-damage, we classify
// statically: a method is GAMEPLAY iff it (transitively) writes model state (a Proto.* field) or calls a known
// combat mutator (Modify*/SetBuff*/Attack/Cast/...). Everything else is PURE-VISUAL.
//
// The classification is CONSERVATIVE toward gameplay: when in doubt → gameplay → run it. Eliding a real gameplay
// effect is the bug; running an extra pure-visual method is harmless. So PURE-VISUAL means PROVABLY no gameplay.
//
//   dotnet Oracle.dll --classify-visual [handfix_list.json]
//
// With a hand-fix list (export via ORACLE_EXPORT_HANDFIXES), it cross-checks: any method we NO-OP that the code
// says is GAMEPLAY is a wrong nop — it silently dropped gameplay. That's the list to convert from nop -> survive.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using ILRuntime.Mono.Cecil;
using ILRuntime.Mono.Cecil.Cil;

namespace YiXianOracle;

internal static class VisualClassifier
{
    static readonly string[] VisualNs = { "UnityEngine", "TMPro", "Spine", "DG.Tweening", "Cinemachine" };
    static bool IsVisual(TypeReference? t) =>
        t != null && VisualNs.Any(v => (t.Namespace ?? "") == v || (t.Namespace ?? "").StartsWith(v + "."));
    static bool IsModel(TypeReference? t) => (t?.Namespace ?? "").StartsWith("Proto");
    // A UI VIEW type by name — its mutator-named methods (SetBuffValue/Refresh…) update DISPLAY, not the model.
    static readonly string[] ViewSuffix = { "UI", "Item", "Panel", "Display", "Label", "Effect", "Animator", "Text", "Layer", "Grid", "View", "Icon", "Bar", "Slot", "Cell" };
    static bool IsViewName(string? n) => n != null && ViewSuffix.Any(s => n.EndsWith(s));

    static Dictionary<string, TypeDefinition> _byName = new();
    static TypeDefinition? Def(TypeReference? t) => t != null && _byName.TryGetValue(t.FullName, out var d) ? d : null;

    // A method DIRECTLY mutates gameplay if it writes model (Proto) state or calls a combat mutator.
    static bool DirectGameplay(MethodDefinition m)
    {
        foreach (var ins in m.Body.Instructions)
        {
            // model write = writing a field declared ON a Proto object (battleTempData.hp = x). NOT a field whose
            // TYPE is Proto on some other object (m_PublicData = publicData is a UI caching a model REF, not a write).
            if ((ins.OpCode == OpCodes.Stfld || ins.OpCode == OpCodes.Stsfld) && ins.Operand is FieldReference f
                && IsModel(f.DeclaringType))
                return true;
            if ((ins.OpCode == OpCodes.Call || ins.OpCode == OpCodes.Callvirt) && ins.Operand is MethodReference mr)
            {
                var n = mr.Name;
                // combat mutators — BUT the method name (SetBuffValue/Modify…) collides between the gameplay
                // entity (BattleCharacter.SetBuffValue -> model) and a VIEW (BuffItem.SetBuffValue -> display).
                // Only count it when the receiver is NOT a UI view, so we don't flag a display update as gameplay.
                bool mutatorName = n.StartsWith("Modify") || n.StartsWith("SetBuff") || n.StartsWith("AddBuff")
                    || n.StartsWith("RemoveBuff") || n is "Attack" or "Cast" or "Heal" or "SetHp" or "AddKeYin"
                    || n is "swapKeYin" or "levelUpKeYin";
                if (mutatorName && !IsViewName(mr.DeclaringType?.Name)) return true;
                // mutation of a Proto model object (set_/Add/Remove/Clear/Insert on a Proto-typed receiver)
                if (IsModel(mr.DeclaringType) && (n.StartsWith("set_") || n is "Add" or "Remove" or "Clear" or "Insert" or "RemoveAt"))
                    return true;
            }
        }
        return false;
    }

    public static void Classify(string dllPath, string? handfixPath, string? emitPath = null)
    {
        var rp = new ReaderParameters { ReadWrite = false, InMemory = true, ReadSymbols = false };
        var module = ModuleDefinition.ReadModule(new MemoryStream(File.ReadAllBytes(dllPath)), rp);
        var allTypes = AllTypes(module).ToList();
        _byName = allTypes.ToDictionary(t => t.FullName, t => t);

        // ── 1. per method: direct-gameplay flag + callees (game methods + async MoveNext) ──
        var methods = allTypes.SelectMany(t => t.Methods).Where(m => m.HasBody).ToList();
        var direct = new HashSet<MethodDefinition>();
        var callers = new Dictionary<MethodDefinition, List<MethodDefinition>>();   // callee -> callers (reverse)
        void Edge(MethodDefinition callee, MethodDefinition caller)
        { if (!callers.TryGetValue(callee, out var l)) callers[callee] = l = new(); l.Add(caller); }

        foreach (var m in methods)
        {
            if (DirectGameplay(m)) direct.Add(m);
            foreach (var ins in m.Body.Instructions)
            {
                if ((ins.OpCode == OpCodes.Call || ins.OpCode == OpCodes.Callvirt || ins.OpCode == OpCodes.Newobj)
                    && ins.Operand is MethodReference mr && !IsVisual(mr.DeclaringType))
                {
                    var dt = Def(mr.DeclaringType);
                    var callee = dt?.Methods.FirstOrDefault(x => x.Name == mr.Name && x.Parameters.Count == mr.Parameters.Count && x.HasBody);
                    if (callee != null) Edge(callee, m);
                }
            }
            // async: the kickoff's gameplay lives in <Name>d__N.MoveNext — link MoveNext as a callee of the kickoff
            var sm = m.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name == "AsyncStateMachineAttribute");
            if (sm != null && sm.ConstructorArguments.Count > 0 && sm.ConstructorArguments[0].Value is TypeReference smRef)
                foreach (var mv in Def(smRef)?.Methods.Where(x => x.Name == "MoveNext" && x.HasBody) ?? Enumerable.Empty<MethodDefinition>())
                    Edge(mv, m);
        }

        // ── 2. propagate: a method is GAMEPLAY if it (transitively) calls a direct-gameplay method ──
        var gameplay = new HashSet<MethodDefinition>(direct);
        var stack = new Stack<MethodDefinition>(direct);
        while (stack.Count > 0)
        {
            var g = stack.Pop();
            if (!callers.TryGetValue(g, out var cs)) continue;
            foreach (var c in cs) if (gameplay.Add(c)) stack.Push(c);
        }

        int total = methods.Count, gp = gameplay.Count, pv = total - gp;
        Console.WriteLine($"=== visual-vs-gameplay classification (read, not run) ===");
        Console.WriteLine($"  methods with body: {total}");
        Console.WriteLine($"  GAMEPLAY (write model / call a mutator, transitively): {gp}  ({direct.Count} direct, {gp - direct.Count} via callgraph)");
        Console.WriteLine($"  PURE-VISUAL (provably no gameplay → safe to neutralize): {pv}");

        // ── 3. cross-check the hand-nop list: any nopped method that is GAMEPLAY = a WRONG nop (dropped gameplay) ──
        if (handfixPath != null && File.Exists(handfixPath))
        {
            var fixes = JsonSerializer.Deserialize<List<HandFix>>(File.ReadAllText(handfixPath),
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? new();
            var nops = fixes.Where(f => f.action == "nop").ToList();
            var wrong = new List<string>();
            int ok = 0;
            foreach (var hf in nops)
            {
                var t = allTypes.FirstOrDefault(x => x.Name == hf.type);
                var ms = t?.Methods.Where(x => x.Name == hf.method && x.HasBody).ToList() ?? new();
                if (ms.Count == 0) continue;
                if (ms.Any(x => gameplay.Contains(x)))
                    wrong.Add($"{hf.type}.{hf.method}  [{(ms.Any(x => direct.Contains(x)) ? "DIRECT — mutates the model itself" : "transitive — reaches a mutator via a call")}]");
                else ok++;
            }
            Console.WriteLine($"\n  hand-nop list: {nops.Count} entries  ->  {ok} provably PURE-VISUAL (nop is fine),  {wrong.Count} are GAMEPLAY (WRONG nop — drops gameplay, convert to survive):");
            foreach (var w in wrong) Console.WriteLine($"    !! {w}");

            // IMPLEMENT THE SOLUTION FROM DETECTION: emit an auto_patch spec that reproduces the hand visual layer
            // as DATA — but flips every nop the classifier proved is GAMEPLAY to "survive" (run real, elide render).
            // Run with ORACLE_HAND_NOPS=0 + ORACLE_AUTO_PATCH=<this> to replace the hand layer with the derived one.
            if (emitPath != null)
            {
                bool IsGameplayFix(HandFix hf)
                {
                    var t = allTypes.FirstOrDefault(x => x.Name == hf.type);
                    var ms = t?.Methods.Where(x => x.Name == hf.method && x.HasBody).ToList() ?? new();
                    return ms.Any(x => gameplay.Contains(x));
                }
                var specs = fixes.Select(hf => new {
                    type = hf.type, method = hf.method, sig = "",
                    action = (hf.action == "nop" && IsGameplayFix(hf)) ? "survive" : hf.action,
                }).ToList();
                File.WriteAllText(emitPath, JsonSerializer.Serialize(specs, new JsonSerializerOptions { WriteIndented = true }));
                Console.WriteLine($"\n  emitted {specs.Count} derived patch specs -> {emitPath}  ({specs.Count(s => s.action == "survive")} survive, {specs.Count(s => s.action == "nop")} nop, {specs.Count(s => s.action == "stub")} stub)");
            }
        }
    }

    class HandFix { public string type { get; set; } = ""; public string method { get; set; } = ""; public string action { get; set; } = ""; }

    static IEnumerable<TypeDefinition> AllTypes(ModuleDefinition m)
    { foreach (var t in m.Types) { yield return t; foreach (var n in Nested(t)) yield return n; } }
    static IEnumerable<TypeDefinition> Nested(TypeDefinition t)
    { foreach (var n in t.NestedTypes) { yield return n; foreach (var nn in Nested(n)) yield return nn; } }
}
