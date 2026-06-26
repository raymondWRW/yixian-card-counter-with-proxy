// AutoPatch — algorithmic, data-driven replacement for the hand-written nop+restore grind in DllPatcher.
//
// THE PRINCIPLE: "headless == the real game with INERT visuals." Types exist (FacadeGen), visual objects
// exist but are non-null no-ops, and serialization round-trips are identity. Under those conditions the
// method's ORIGINAL body runs and its gameplay survives *by construction* — we never delete it.
//
// So instead of nop-then-handcode-restore, we:
//   1. RESTORE the method's original IL body (cross-module clone from the unpatched DLL bytes), then
//   2. apply SURVIVE-HEADLESS transforms that neutralize ONLY the headless-breaking instructions:
//        - lazy-non-null visual `ldfld`/`ldsfld` reads (generalizes the hand get_cardInfo / lazy fixes)
//        - identity-elide curated round-trip calls (NetworkExtensions.Clone<T>(x) -> x; its ProtobufParser
//          stub returns null, but in the real game Clone is a value-identity copy for our read-only configs)
//   3. NEVER nop it.
// The bit-exact sweep is the oracle that accepts/rejects each restore; the DETECTOR below finds which nops
// dropped gameplay so the loop knows what to restore.
//
// Driven by a JSON spec (env ORACLE_AUTO_PATCH=<path>); inert when unset, so it can't disturb the main path.
//   [ { "type":"CardItem", "method":"InitData", "sig":"Int32,CardUseType,Int32,Dictionary`2,String",
//       "action":"survive" }, ... ]      // action: survive (default) | nop | stub
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using ILRuntime.Mono.Cecil;
using ILRuntime.Mono.Cecil.Cil;

namespace YiXianOracle;

internal static class AutoPatch
{
    // Namespaces whose types are visual/headless-inert (NOT Cysharp — UniTask is async gameplay infra).
    static readonly string[] VisualNs = { "UnityEngine", "TMPro", "Spine", "DG.Tweening", "Cinemachine" };
    static bool IsVisualType(TypeReference? t)
    {
        if (t == null || t.IsValueType || t.IsGenericParameter) return false;
        var ns = t.Namespace ?? "";
        return VisualNs.Any(v => ns == v || ns.StartsWith(v + "."));
    }
    // A Unity SCENE OBJECT: a class whose base chain reaches UnityEngine.Object/Component/Behaviour/MonoBehaviour.
    // GAME-defined ones (HpBarTweenEffect, DefItem, CharacterBattleAnimator, ...) are serialized references that
    // are NULL headless (Unity never deserialized the prefab) — so a field of this type loads null and the next
    // member access NREs. Used ONLY for the lazy-non-null FIELD path (substitute a stub), never for call-elision:
    // the owning object itself (e.g. BattleCharacterUI, also a MonoBehaviour) is non-null and holds gameplay we keep.
    static bool IsSceneObject(TypeReference? t)
    {
        if (t == null || t.IsValueType || t.IsGenericParameter || t.IsArray) return false;
        try
        {
            for (var d = t.Resolve(); d != null; d = d.BaseType?.Resolve())
            {
                var fn = d.FullName;
                if (fn is "UnityEngine.Object" or "UnityEngine.Component" or "UnityEngine.Behaviour" or "UnityEngine.MonoBehaviour")
                    return true;
            }
        }
        catch { }
        return false;
    }
    // Curated "identity in headless" calls: the call's result should be its (single) argument unchanged.
    static bool IsIdentityCall(MethodReference m) =>
        m.Name == "Clone" && m.DeclaringType?.Name == "NetworkExtensions" && m.Parameters.Count == 1;

    // Gameplay-write detector: does this body mutate game state (vs. pure visual)?  Used to flag overbroad nops.
    static bool HasGameplayWrite(MethodDefinition m)
    {
        if (!m.HasBody) return false;
        foreach (var ins in m.Body.Instructions)
        {
            if ((ins.OpCode == OpCodes.Stfld || ins.OpCode == OpCodes.Stsfld) && ins.Operand is FieldReference f
                && !IsVisualType(f.FieldType)
                && ((f.DeclaringType?.Namespace ?? "").StartsWith("Proto") || (f.FieldType.Namespace ?? "").StartsWith("Proto")))
                return true;
            if ((ins.OpCode == OpCodes.Call || ins.OpCode == OpCodes.Callvirt) && ins.Operand is MethodReference mr
                && (mr.Name is "FindCardConfig" or "set_cardConfig" or "set_sourceCardConfig" or "set_useType"
                    || mr.Name.StartsWith("Modify") || mr.Name.StartsWith("SetBuff")))
                return true;
        }
        return false;
    }

    /// <summary>Precise overbroad-nop detector: a method whose ORIGINAL body writes gameplay state but whose
    /// CURRENT (patched) body in <paramref name="patched"/> has LOST that write — i.e. a nop/stub that
    /// silently dropped gameplay. Live methods (gameplay still present after patching) and already-restored
    /// ones drop off the list automatically. Returns "Type.Method(sig)" strings ready for an auto_patch spec.</summary>
    internal static List<string> DetectOverbroadNops(byte[] originalDllBytes, ModuleDefinition patched, IEnumerable<string> typeNames)
    {
        var orig = ModuleDefinition.ReadModule(new MemoryStream(originalDllBytes),
            new ReaderParameters { ReadWrite = false, InMemory = true, ReadSymbols = false });
        var names = new HashSet<string>(typeNames);
        var hits = new List<string>();
        foreach (var t in AllTypes(orig).Where(t => names.Contains(t.Name)))
            foreach (var m in t.Methods.Where(m => m.HasBody && !m.IsConstructor && HasGameplayWrite(m)))
            {
                var sig = string.Join(",", m.Parameters.Select(p => p.ParameterType.Name));
                var cur = FindMethod(patched, t.Name, m.Name, sig);
                if (cur != null && !HasGameplayWrite(cur))   // patch removed the gameplay -> overbroad nop
                    hits.Add($"{t.Name}.{m.Name}({sig})");
            }
        return hits;
    }

    /// <summary>Apply the JSON spec at specPath (if set/exists). originalDllBytes is the UNPATCHED DLL, used
    /// to restore original bodies regardless of any prior nop in the same patch run.</summary>
    internal static void Apply(ModuleDefinition module, byte[] originalDllBytes, string? specPath)
    {
        if (string.IsNullOrEmpty(specPath) || !File.Exists(specPath)) return;
        List<Spec>? specs;
        try { specs = JsonSerializer.Deserialize<List<Spec>>(File.ReadAllText(specPath),
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true }); }
        catch (Exception e) { Console.WriteLine($"  [auto-patch] WARN: bad spec {specPath}: {e.Message}"); return; }
        if (specs == null || specs.Count == 0) return;
        var orig = ModuleDefinition.ReadModule(new MemoryStream(originalDllBytes),
            new ReaderParameters { ReadWrite = false, InMemory = true, ReadSymbols = false });
        int n = 0;
        foreach (var s in specs)
        {
            // sig empty => apply to ALL overloads of this name (mirrors DllPatcher.NopType's by-name semantics).
            // The hand layer nops every overload; matching only cands[0] left visual overloads LIVE — e.g. an
            // async UI-init overload still ran <LateInitAsync>d__N.MoveNext and NRE'd, which is exactly why
            // replaying the exported hand layer as data only reached 11.2%. Patch them all.
            var targets = FindMethods(module, s.Type, s.Method, s.Sig);
            if (targets.Count == 0) { Console.WriteLine($"  [auto-patch] WARN: {s.Type}.{s.Method}({s.Sig}) not found"); continue; }
            var action = (s.Action ?? "survive").ToLowerInvariant();
            foreach (var target in targets)
            switch (action)
            {
                case "nop": DllPatcher.NopMethod(target); n++; break;
                case "stub": DllPatcher.ReturnNonNullStub(module, target); n++; break;
                default: // "survive": (restore original body if it was nopped, then) neutralize visual instrs.
                    // match the ORIGINAL overload by exact signature so multi-overload survive pairs correctly.
                    var tsig = string.Join(",", target.Parameters.Select(p => p.ParameterType.Name));
                    var src = FindMethod(orig, s.Type, s.Method, tsig);
                    if (src == null || !src.HasBody) { Console.WriteLine($"  [auto-patch] WARN: no original body for {s.Type}.{s.Method}"); break; }
                    // Only re-clone from the unpatched module if the target was actually nopped/shrunk. An
                    // UN-nopped method (e.g. the combat state machine <Execute>d__52, never in the nop list)
                    // ALREADY has its original body in-module — re-cloning it cross-module is pointless AND trips
                    // the vendored Cecil importer's generic-type bug (List`1 mis-scope / write NRE). So skip the
                    // restore when the body is intact and just run SurviveHeadless on it directly.
                    if (target.Body.Instructions.Count < src.Body.Instructions.Count)
                        RestoreOriginalBody(module, target, src);
                    SurviveHeadless(module, target);
                    n++;
                    break;
            }
        }
        if (n > 0) Console.WriteLine($"  [auto-patch] applied {n} data-driven patch(es) from {Path.GetFileName(specPath)}");
    }

    // --- survive-headless transform: neutralize ONLY the headless-breaking instructions ---------------------
    // Strategy: an init/visual method's gameplay is its DATA stores (stfld of non-visual fields, gameplay
    // calls). What breaks headless is its VISUAL work: (a) calls into UnityEngine/TMPro/... types whose facade
    // can't fully implement them (JIT TypeLoad), and (b) null serialized UI field derefs (NRE). So we ELIDE
    // every visual-type method call/newobj (pop its args, push default(return)) and lazy-non-null visual field
    // reads. The data stores are never touched, so gameplay survives by construction; the bit-exact sweep
    // rejects any elision that actually changed a gameplay value. This generalizes the four hand-written
    // "nop InitData then re-add gameplay essentials" patches into one rule.
    static readonly bool _noElide = Environment.GetEnvironmentVariable("ORACLE_SURVIVE_NO_ELIDE") == "1";
    static readonly bool _noLazyNull = Environment.GetEnvironmentVariable("ORACLE_SURVIVE_NO_LAZYNULL") == "1";
    static readonly bool _nnGuard = Environment.GetEnvironmentVariable("ORACLE_SURVIVE_NN_GUARD") == "1";   // branch-free deref guard (works on async state machines)

    // Inject (once per module) a helper `object __OracleNN(object x, RuntimeTypeHandle h)` = x is non-null ? x :
    // GetUninitializedObject(typeFromHandle(h)). The null-check is INSIDE the helper so call sites stay branch-free.
    static MethodReference EnsureNNHelper(ModuleDefinition module)
    {
        var existing = module.GetType("__OracleHelpers");
        if (existing != null)
        {
            var m0 = existing.Methods.FirstOrDefault(m => m.Name == "__OracleNN");
            if (m0 != null) return m0;
        }
        var t = existing ?? new TypeDefinition("", "__OracleHelpers",
            TypeAttributes.Public | TypeAttributes.Abstract | TypeAttributes.Sealed | TypeAttributes.Class, module.TypeSystem.Object);
        if (existing == null) module.Types.Add(t);
        var nn = new MethodDefinition("__OracleNN",
            MethodAttributes.Public | MethodAttributes.Static | MethodAttributes.HideBySig, module.TypeSystem.Object);
        nn.Parameters.Add(new ParameterDefinition("x", ParameterAttributes.None, module.TypeSystem.Object));
        nn.Parameters.Add(new ParameterDefinition("h", ParameterAttributes.None, module.ImportReference(typeof(RuntimeTypeHandle))));
        var gtfh = module.ImportReference(typeof(Type).GetMethod("GetTypeFromHandle", new[] { typeof(RuntimeTypeHandle) }));
        var gu = module.ImportReference(typeof(System.Runtime.CompilerServices.RuntimeHelpers).GetMethod("GetUninitializedObject", new[] { typeof(Type) }));
        var il = nn.Body.GetILProcessor();
        var ret = il.Create(OpCodes.Ret);
        il.Append(il.Create(OpCodes.Ldarg_0));            // x
        il.Append(il.Create(OpCodes.Dup));                // x x
        il.Append(il.Create(OpCodes.Brtrue, ret));        // x!=null -> ret (x on stack)
        il.Append(il.Create(OpCodes.Pop));                // drop null
        il.Append(il.Create(OpCodes.Ldarg_1));            // h
        il.Append(il.Create(OpCodes.Call, gtfh));         // Type
        il.Append(il.Create(OpCodes.Call, gu));           // ctor-skipped non-null instance
        il.Append(ret);
        t.Methods.Add(nn);
        return nn;
    }

    // THE MOCK PASS (ORACLE_MOCK_UI=1): turn every UI component into a functional headless state CELL instead of
    // bypassing it. For each UI/scene-object type, SURVIVE its property accessors (get_/set_) — run the real
    // backing-field store/load, elide only the rendering. So `characterUI.tempLife += x` actually lands and the
    // engine tracks UI-owned combat state through the (now functional) component. Generalizes the hand
    // set_tempLife rewrite into one rule, auto-detected (any accessor on any view type). Accessors are simple
    // (load/store +/- render), so this is far safer than blanket-surviving whole methods.
    internal static int MockUiAccessors(ModuleDefinition module)
    {
        int n = 0, types = 0;
        foreach (var t in AllTypes(module).ToList())
        {
            if (IsVisualType(t) || !DerivesFromSceneBase(t)) continue;
            types++;
            foreach (var m in t.Methods.ToList())
            {
                if (!m.HasBody || m.IsConstructor || m.IsStatic || m.Parameters.Count != 1) continue;
                if (!m.Name.StartsWith("set_")) continue;   // the WRITE side — make it a pure store cell
                // EXTRACT THE STORE: a UI setter is `m_X = value; <render>`. Don't transform the messy body
                // (DOTween/label control flow doesn't elide cleanly -> bad IL). Find the backing-field store of the
                // VALUE and REBUILD the setter as just that store — a clean, functional state cell. This is the
                // hand set_tempLife rewrite, generalized to every UI setter, auto-detected.
                var pt = m.Parameters[0].ParameterType;
                var store = m.Body.Instructions
                    .Where(i => i.OpCode == OpCodes.Stfld && i.Operand is FieldReference f
                                && !IsVisualType(f.FieldType) && f.FieldType.FullName == pt.FullName)
                    .Select(i => (FieldReference)i.Operand).FirstOrDefault();
                if (store == null) continue;   // no clean param-typed backing store -> leave it (visual-only setter)
                var b = m.Body;
                b.Instructions.Clear(); b.ExceptionHandlers.Clear(); b.Variables.Clear();
                var il = b.GetILProcessor();
                il.Append(il.Create(OpCodes.Ldarg_0));
                il.Append(il.Create(OpCodes.Ldarg_1));
                il.Append(il.Create(OpCodes.Stfld, store));
                il.Append(il.Create(OpCodes.Ret));
                n++;
            }
        }
        Console.WriteLine($"  [mock-ui] rebuilt {n} UI setters as pure state cells (store backing field, render dropped) across {types} components");
        return n;
    }

    // Name-walk the base chain (Resolve() is flaky on the in-memory module) — true if t is a UI/scene component.
    static bool DerivesFromSceneBase(TypeDefinition t)
    {
        TypeReference? cur = t.BaseType;
        for (int i = 0; i < 32 && cur != null; i++)
        {
            if (cur.Name is "MonoBehaviour" or "Component" or "Behaviour" or "ILRComponentBase" or "ILRPanelBase") return true;
            TypeDefinition? d = null; try { d = cur.Resolve(); } catch { }
            cur = d?.BaseType;
        }
        return false;
    }

    static void SurviveHeadless(ModuleDefinition module, MethodDefinition m)
    {
        if (!m.HasBody) return;
        // ASYNC: an `async` method's body is just the builder kickoff — the real code (and any NRE) lives in the
        // compiler-generated <Name>d__N.MoveNext. So surviving the kickoff alone does nothing; follow the
        // [AsyncStateMachine] and survive the MoveNext (where the gameplay + visual calls actually are).
        var asm = m.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name == "AsyncStateMachineAttribute");
        if (asm != null && asm.ConstructorArguments.Count > 0 && asm.ConstructorArguments[0].Value is TypeReference smRef)
        {
            var smt = AllTypes(module).FirstOrDefault(t => t.FullName == smRef.FullName);
            if (smt != null) foreach (var mv in smt.Methods.Where(x => x.Name == "MoveNext" && x.HasBody)) SurviveHeadless(module, mv);
        }
        var il = m.Body.GetILProcessor();
        // Lazy-null inserts `dup;brtrue;pop;stub` after an ldfld. On a large async state-machine MoveNext
        // (deep control flow + builder try/catch) this reliably produces invalid IL (InvalidProgramException),
        // and it isn't needed there: ELIDING visual calls runs the machine fine, and any null-receiver deref is
        // fixed by stubbing the NULL-SOURCE method as its own spec (the auto_heal cascade). So for compiler
        // state machines we ELIDE only and skip lazy-null. (Simple init methods like InitData still lazy-null.)
        bool isStateMachine = (m.DeclaringType?.Name?.Contains(">d__") ?? false)
                              || (m.Name == "MoveNext" && (m.DeclaringType?.Name?.StartsWith("<") ?? false));
        foreach (var ins in m.Body.Instructions.ToList())
        {
            if (_noElide && (ins.OpCode == OpCodes.Call || ins.OpCode == OpCodes.Callvirt || ins.OpCode == OpCodes.Newobj)) continue;
            // identity-elide: `call Clone<T>(x)` -> nop (x passes through unchanged)
            if ((ins.OpCode == OpCodes.Call || ins.OpCode == OpCodes.Callvirt)
                && ins.Operand is MethodReference idm && IsIdentityCall(idm))
            { il.Replace(ins, il.Create(OpCodes.Nop)); continue; }
            // elide a call/callvirt to a VISUAL-type method: it would JIT-TypeLoad (missing facade impl) or
            // NRE on a null UI receiver. Pop receiver+args, push default(return). Mutate the instruction in
            // place (don't Replace) so branch targets / exception-handler boundaries pointing at it stay valid.
            if ((ins.OpCode == OpCodes.Call || ins.OpCode == OpCodes.Callvirt)
                && ins.Operand is MethodReference vm && IsVisualType(vm.DeclaringType))
            { ElideVisualCall(module, m, il, ins, vm); continue; }
            // GENERAL visual-method elision: a GAME method with NO gameplay write and a void return is
            // visual-only (e.g. KeYinCardItem.ToRootParent/ResetMoveableRect called by ShowCardInBattle).
            // Surviving the caller runs these for real and they break headless (null transforms etc.), so
            // elide them too — extends "visual == external namespace" to "visual == provably no gameplay
            // effect". Gated until validated. Value/async returns are kept (combat may read them).
            if (_elideVisualMethods && (ins.OpCode == OpCodes.Call || ins.OpCode == OpCodes.Callvirt)
                && ins.Operand is MethodReference gm && IsVisualOnlyGameMethod(module, gm))
            { ElideVisualCall(module, m, il, ins, gm); continue; }
            // elide newobj of a VISUAL type (pop ctor args, push null — the new ref): same TypeLoad risk.
            if (ins.OpCode == OpCodes.Newobj && ins.Operand is MethodReference vc && IsVisualType(vc.DeclaringType))
            { ElideCall(module, m, il, ins, vc.Parameters.Count, vc.DeclaringType); continue; }
            // lazy-non-null: after `ldfld/ldsfld F` of ANY stubbable reference field, if the loaded value is
            // null substitute a non-null inert stub so the following member access doesn't NRE. Headless the
            // owning UI object is ctor-skipped, so ALL its serialized refs are null; this revives them inertly.
            // Crucially it only fires when the value IS null — non-null gameplay state we seeded (the deck
            // battleCardItems, etc.) flows through untouched. The bit-exact sweep rejects any stub that
            // perturbs a gameplay value, so over-stubbing is self-correcting.
            if (!_noLazyNull && (ins.OpCode == OpCodes.Ldfld || ins.OpCode == OpCodes.Ldsfld)
                && ins.Operand is FieldReference fr && Stubbable(fr.FieldType) && !IsAsyncInfra(fr) && ins.Next != null)
            {
                if (_nnGuard)
                {
                    // BRANCH-FREE guard: `value` -> `value ?? stub` via a helper call. The null-check lives INSIDE
                    // the helper, so the call site adds NO branches — IL-verifiable even inside an async state
                    // machine (where the inline dup/brtrue/pop version produces InvalidProgramException, which is
                    // why lazy-null was skipped there). So we can guard EVERY stubbable deref, including async.
                    var nn = EnsureNNHelper(module);
                    var ft = module.ImportReference(fr.FieldType);
                    var a = il.Create(OpCodes.Ldtoken, ft);
                    var b = il.Create(OpCodes.Call, nn);
                    var c = il.Create(OpCodes.Castclass, ft);
                    il.InsertAfter(ins, a); il.InsertAfter(a, b); il.InsertAfter(b, c);
                }
                else if (!isStateMachine)
                {
                    var cont = ins.Next;                       // non-null path / original successor
                    var dup = il.Create(OpCodes.Dup);
                    var br = il.Create(OpCodes.Brtrue, cont);
                    var pop = il.Create(OpCodes.Pop);
                    il.InsertAfter(ins, dup); il.InsertAfter(dup, br); il.InsertAfter(br, pop);
                    EmitStubAfter(module, il, pop, fr.FieldType);   // pushes a non-null stub of the field type
                }
            }
        }
    }

    // Central rule for the "gameplay trapped in a visual callback" class (e.g. swapKeYin's gameplay inside a
    // DOTween OnComplete delegate that the elided tween call would drop): when eliding a visual CALL, FIRE any
    // parameterless delegate argument (TweenCallback/Action) null-safely instead of discarding it, so its
    // gameplay runs. Non-delegate args are popped as before. Default-off (ORACLE_SURVIVE_FIRE_CALLBACKS=1) until
    // validated, so the 100% HD path is untouched.
    static readonly bool _fireCallbacks = Environment.GetEnvironmentVariable("ORACLE_SURVIVE_FIRE_CALLBACKS") != "0";   // default ON (validated HD/KeYin/Dream/full-corpus); =0 disables
    static readonly bool _elideVisualMethods = Environment.GetEnvironmentVariable("ORACLE_SURVIVE_ELIDE_VISUAL_METHODS") == "1";

    // A GAME method that is provably visual-only: same-module, has a body, writes NO gameplay state
    // (HasGameplayWrite false), and returns void or a visual type (so eliding it drops no value combat reads).
    // This is the general form of "visual call" — not limited to external namespaces.
    static bool IsVisualOnlyGameMethod(ModuleDefinition module, MethodReference mr)
    {
        if (mr == null || mr.DeclaringType == null || IsVisualType(mr.DeclaringType)) return false;
        if (mr.Name is "Invoke" || (mr.Name?.StartsWith("get_") ?? false)) return false;  // never elide getters/delegate invokes
        MethodDefinition? def;
        try { def = mr.Resolve(); } catch { return false; }
        if (def == null || def.Module != module || !def.HasBody || def.IsConstructor) return false;
        var rt = def.ReturnType;
        if (!(rt.MetadataType == MetadataType.Void || IsVisualType(rt))) return false;  // keep value/async returns
        return !HasGameplayWrite(def);
    }

    static void ElideVisualCall(ModuleDefinition module, MethodDefinition m, ILProcessor il, Instruction ins, MethodReference vm)
    {
        int nConsume = vm.Parameters.Count + (vm.HasThis ? 1 : 0);
        if (!_fireCallbacks) { ElideCall(module, m, il, ins, nConsume, vm.ReturnType); return; }
        // Stack top -> bottom: last param, ..., first param, [receiver]. Handle each slot.
        var slots = new List<TypeReference?>();
        for (int i = vm.Parameters.Count - 1; i >= 0; i--) slots.Add(vm.Parameters[i].ParameterType);
        if (vm.HasThis) slots.Add(null);                       // receiver is never a delegate
        ins.OpCode = OpCodes.Nop; ins.Operand = null;          // keep branch/handler anchors valid; build after it
        var cur = ins;
        void Add(Instruction x) { il.InsertAfter(cur, x); cur = x; }
        foreach (var st in slots)
        {
            if (IsParameterlessDelegate(st, out var invoke))
            {
                var lcall = il.Create(OpCodes.Nop);
                var ldone = il.Create(OpCodes.Nop);
                Add(il.Create(OpCodes.Dup));
                Add(il.Create(OpCodes.Brtrue, lcall));
                Add(il.Create(OpCodes.Pop));                   // null delegate -> just drop it
                Add(il.Create(OpCodes.Br, ldone));
                Add(lcall);
                Add(il.Create(OpCodes.Callvirt, module.ImportReference(invoke)));  // non-null -> run its gameplay
                Add(ldone);
            }
            else Add(il.Create(OpCodes.Pop));
        }
        var rt = vm.ReturnType;
        if (rt != null && rt.MetadataType != MetadataType.Void)
        {
            if (rt.IsValueType || rt.IsGenericParameter)
            {
                var rti = module.ImportReference(rt);
                var tmp = new VariableDefinition(rti); m.Body.Variables.Add(tmp);
                Add(il.Create(OpCodes.Ldloca, tmp)); Add(il.Create(OpCodes.Initobj, rti)); Add(il.Create(OpCodes.Ldloc, tmp));
            }
            else Add(il.Create(OpCodes.Ldnull));
        }
    }

    // A void, zero-arg delegate type (TweenCallback, Action, UnityAction, ...) whose body we can invoke directly.
    static bool IsParameterlessDelegate(TypeReference? t, out MethodReference invoke)
    {
        invoke = null!;
        if (t == null || t.IsValueType || t.IsGenericParameter || t.IsArray) return false;
        try
        {
            var d = t.Resolve(); if (d == null) return false;
            bool isDel = false;
            for (var b = d.BaseType?.Resolve(); b != null; b = b.BaseType?.Resolve())
                if (b.FullName is "System.MulticastDelegate" or "System.Delegate") { isDel = true; break; }
            if (!isDel) return false;
            var inv = d.Methods.FirstOrDefault(x => x.Name == "Invoke");
            if (inv == null || inv.Parameters.Count != 0 || inv.ReturnType.MetadataType != MetadataType.Void) return false;
            invoke = inv; return true;
        }
        catch { return false; }
    }

    // Turn a visual call/newobj at `ins` into a stack-neutral elision: consume `nConsume` stack slots
    // (receiver + args, or ctor args) and push default(retType). `ins` is mutated in place to the first pop
    // (or nop) so any branch/handler that targets it remains anchored; the rest is inserted after it.
    static void ElideCall(ModuleDefinition module, MethodDefinition m, ILProcessor il, Instruction ins, int nConsume, TypeReference retType)
    {
        var after = new List<Instruction>();
        if (nConsume <= 0) { ins.OpCode = OpCodes.Nop; ins.Operand = null; }
        else { ins.OpCode = OpCodes.Pop; ins.Operand = null; for (int i = 1; i < nConsume; i++) after.Add(il.Create(OpCodes.Pop)); }
        if (retType != null && retType.MetadataType != MetadataType.Void)
        {
            if (retType.IsValueType || retType.IsGenericParameter)
            {
                var rt = module.ImportReference(retType);
                var tmp = new VariableDefinition(rt); m.Body.Variables.Add(tmp);
                after.Add(il.Create(OpCodes.Ldloca, tmp));
                after.Add(il.Create(OpCodes.Initobj, rt));
                after.Add(il.Create(OpCodes.Ldloc, tmp));
            }
            else after.Add(il.Create(OpCodes.Ldnull));
        }
        var cur = ins;
        foreach (var a in after) { il.InsertAfter(cur, a); cur = a; }
    }

    // Async state-machine INFRASTRUCTURE field — must NOT be lazy-nulled (substituting a stub for a null
    // builder/awaiter/state corrupts the state machine -> invalid IL / TypeLoad). These are the compiler
    // `<>`-prefixed fields (`<>t__builder`, `<>u__1`, `<>1__state`, `<>4__this`) and any awaiter/builder/Task
    // typed field. Hoisted USER locals like `<battlePanel>5__3` (named `<ident>N__M`, not `<>...`) are NOT infra
    // and DO get lazy-nulled (that's how surviving a combat state machine fixes its null UI-panel derefs).
    static bool IsAsyncInfra(FieldReference fr)
    {
        if (fr.Name.StartsWith("<>")) return true;
        var ns = fr.FieldType?.Namespace ?? "";
        if (ns == "System.Runtime.CompilerServices" || ns.StartsWith("Cysharp.Threading.Tasks") || ns == "System.Threading.Tasks")
            return true;
        var tn = fr.FieldType?.Name ?? "";
        return tn.Contains("Awaiter") || tn.Contains("Builder") || tn == "Task" || tn.StartsWith("Task`");
    }

    static bool Stubbable(TypeReference rt)
    {
        // Exclude generic instances (List<T> etc.): EmitStubAfter would module.ImportReference the generic type
        // for ldtoken/castclass, tripping the vendored Cecil importer's generic bug -> invalid IL. They're also
        // almost always non-null gameplay collections (lazy-null wouldn't fire), so skipping them is safe.
        if (rt.IsValueType || rt.IsArray || rt.IsGenericParameter || rt is GenericInstanceType || rt.FullName == "System.String") return false;
        var d = rt.Resolve();
        return d is { IsInterface: false, IsAbstract: false };
    }

    // Append (after `anchor`) the instructions that push a non-null stub instance of rt. Facade types with a
    // parameterless ctor -> newobj (runs the facade ctor); game/other types -> GetUninitializedObject (ctor-skipped).
    static void EmitStubAfter(ModuleDefinition module, ILProcessor il, Instruction anchor, TypeReference rt)
    {
        var def = rt.Resolve();
        bool isGameType = def != null && def.Module == il.Body.Method.Module;
        MethodReference? ctor = isGameType ? null
            : def?.Methods.FirstOrDefault(c => c.IsConstructor && !c.IsStatic && c.Parameters.Count == 0 && (c.IsPublic || c.IsAssembly)) is { } pc
                ? module.ImportReference(pc) : null;
        var seq = new List<Instruction>();
        if (ctor != null) seq.Add(il.Create(OpCodes.Newobj, ctor));
        else
        {
            var gtfh = module.ImportReference(typeof(Type).GetMethod("GetTypeFromHandle", new[] { typeof(RuntimeTypeHandle) }));
            var gu = module.ImportReference(typeof(System.Runtime.CompilerServices.RuntimeHelpers).GetMethod("GetUninitializedObject", new[] { typeof(Type) }));
            seq.Add(il.Create(OpCodes.Ldtoken, module.ImportReference(rt)));
            seq.Add(il.Create(OpCodes.Call, gtfh));
            seq.Add(il.Create(OpCodes.Call, gu));
            seq.Add(il.Create(OpCodes.Castclass, module.ImportReference(rt)));
        }
        var cur = anchor;
        foreach (var s in seq) { il.InsertAfter(cur, s); cur = s; }
    }

    // --- cross-module original-body clone ------------------------------------------------------------------
    static void RestoreOriginalBody(ModuleDefinition module, MethodDefinition target, MethodDefinition orig)
    {
        var tb = target.Body;
        tb.Instructions.Clear(); tb.Variables.Clear(); tb.ExceptionHandlers.Clear();
        tb.InitLocals = orig.Body.InitLocals;
        foreach (var v in orig.Body.Variables)
            tb.Variables.Add(new VariableDefinition(module.ImportReference(v.VariableType)));
        var il = tb.GetILProcessor();
        var map = new Dictionary<Instruction, Instruction>();
        foreach (var ins in orig.Body.Instructions)
        {
            var ni = CloneInstr(module, il, target, tb, ins);
            map[ins] = ni; il.Append(ni);
        }
        foreach (var ni in tb.Instructions)
        {
            if (ni.Operand is Instruction t && map.TryGetValue(t, out var nt)) ni.Operand = nt;
            else if (ni.Operand is Instruction[] arr) ni.Operand = arr.Select(x => map[x]).ToArray();
        }
        foreach (var eh in orig.Body.ExceptionHandlers)
            tb.ExceptionHandlers.Add(new ExceptionHandler(eh.HandlerType)
            {
                CatchType = eh.CatchType != null ? module.ImportReference(eh.CatchType) : null,
                TryStart = map[eh.TryStart], TryEnd = map[eh.TryEnd],
                HandlerStart = map[eh.HandlerStart], HandlerEnd = map[eh.HandlerEnd],
                FilterStart = eh.FilterStart != null ? map[eh.FilterStart] : null,
            });
    }

    // NOTE: surviving a method with GENERIC-INSTANCE memberrefs/locals (e.g. the <Execute>d__52 combat state
    // machine, which has List<GameType> locals) is blocked at the Cecil-DEPENDENCY layer: this vendored
    // ILRuntime.Mono.Cecil fork's DefaultMetadataImporter both MIS-SCOPES the corlib generic (List`1 -> the
    // game assembly -> TypeLoad) AND NREs in ImportTypeSpecification when writing a hand-rebuilt composite type
    // (Import.cs:648). A manual recursive importer traded the (catchable) TypeLoad for an (uncatchable) write
    // crash, so it was reverted. Surviving the real combat state machine needs a fixed Cecil importer; until
    // then, leave plain ImportReference (TypeLoad surfaces as a normal per-round fault, gracefully rejected).
    static Instruction CloneInstr(ModuleDefinition module, ILProcessor il, MethodDefinition target, MethodBody tb, Instruction ins)
    {
        switch (ins.Operand)
        {
            case MethodReference mr: return il.Create(ins.OpCode, module.ImportReference(mr));
            case FieldReference fr: return il.Create(ins.OpCode, module.ImportReference(fr));
            case TypeReference tr: return il.Create(ins.OpCode, module.ImportReference(tr));
            case VariableDefinition vd: return il.Create(ins.OpCode, tb.Variables[vd.Index]);
            case ParameterDefinition pd: return il.Create(ins.OpCode, target.Parameters[pd.Index]);
            case Instruction t2: return il.Create(ins.OpCode, t2);            // fixed up in second pass
            case Instruction[] arr: return il.Create(ins.OpCode, arr);        // fixed up in second pass
            case string s: return il.Create(ins.OpCode, s);
            case sbyte sb: return il.Create(ins.OpCode, sb);
            case byte b: return il.Create(ins.OpCode, b);
            case int i: return il.Create(ins.OpCode, i);
            case long l: return il.Create(ins.OpCode, l);
            case float fl: return il.Create(ins.OpCode, fl);
            case double d: return il.Create(ins.OpCode, d);
            case null: return il.Create(ins.OpCode);
            default: return il.Create(ins.OpCode);
        }
    }

    static MethodDefinition? FindMethod(ModuleDefinition m, string type, string method, string? sig)
    {
        var t = AllTypes(m).FirstOrDefault(x => x.Name == type || x.FullName == type);
        var cands = t?.Methods.Where(x => x.Name == method && x.HasBody).ToList();
        if (cands == null || cands.Count == 0) return null;
        if (string.IsNullOrEmpty(sig)) return cands[0];
        return cands.FirstOrDefault(x => string.Join(",", x.Parameters.Select(p => p.ParameterType.Name)) == sig) ?? cands[0];
    }

    // Like FindMethod but returns ALL matching overloads when sig is empty (by-name semantics, matching the
    // hand DllPatcher.NopType). With sig given, returns the single best signature match.
    static List<MethodDefinition> FindMethods(ModuleDefinition m, string type, string method, string? sig)
    {
        var t = AllTypes(m).FirstOrDefault(x => x.Name == type || x.FullName == type);
        var cands = t?.Methods.Where(x => x.Name == method && x.HasBody).ToList() ?? new List<MethodDefinition>();
        if (cands.Count == 0 || string.IsNullOrEmpty(sig)) return cands;
        var exact = cands.FirstOrDefault(x => string.Join(",", x.Parameters.Select(p => p.ParameterType.Name)) == sig);
        return exact != null ? new List<MethodDefinition> { exact } : new List<MethodDefinition> { cands[0] };
    }

    static IEnumerable<TypeDefinition> AllTypes(ModuleDefinition m)
    {
        foreach (var t in m.Types) { yield return t; foreach (var n in Nested(t)) yield return n; }
        static IEnumerable<TypeDefinition> Nested(TypeDefinition t)
        { foreach (var n in t.NestedTypes) { yield return n; foreach (var nn in Nested(n)) yield return nn; } }
    }

    class Spec { public string Type { get; set; } = ""; public string Method { get; set; } = ""; public string? Sig { get; set; } public string? Action { get; set; } }
}
