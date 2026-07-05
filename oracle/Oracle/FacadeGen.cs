// Algorithmic facade generation — instead of hand-stubbing each missing type, take Il2CppDumper's
// DummyDll (complete type + signature coverage for EVERY referenced assembly) and Cecil-rewrite every
// method body to "return default". That yields COMPLETE, RUNNABLE facades automatically: every type the
// game references is present (no native binding gaps) and every method safely no-ops. The handful that
// need real behavior (Transform.position, UniTask completion) are layered on top by the hand-written
// UnityStubs facades, which override the generated ones by load order. Per game update: just re-run.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using ILRuntime.Mono.Cecil;
using ILRuntime.Mono.Cecil.Cil;

namespace YiXianOracle;

static class FacadeGen
{
    // Assemblies we do NOT want as facades: the real game DLL (loaded for real) and the framework
    // (CoreCLR provides the real ones). Everything else in DummyDll becomes a default-body facade.
    static readonly string[] Skip = { "DarkSun.HotUpdate", "mscorlib", "netstandard", "System", "Mono.Security" };

    public static void Generate(string dummyDir, string outDir)
    {
        Directory.CreateDirectory(outDir);
        // Resolve inter-DummyDll references (so base-ctor resolution / type refs don't fail mid-generate).
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(dummyDir);
        resolver.ResolveFailure += (s, r) => AssemblyDefinition.CreateAssembly(
            new AssemblyNameDefinition(r.Name, r.Version ?? new Version(0, 0)), r.Name, ModuleKind.Dll);
        int asm = 0, methods = 0;
        foreach (var dll in Directory.GetFiles(dummyDir, "*.dll"))
        {
            var name = Path.GetFileNameWithoutExtension(dll);
            if (Skip.Any(s => name == s || name.StartsWith(s + ".") || name.StartsWith("System.")))
                continue;
            try
            {
                var module = ModuleDefinition.ReadModule(dll, new ReaderParameters { ReadWrite = false, InMemory = true, AssemblyResolver = resolver });
                foreach (var type in AllTypes(module))
                    foreach (var m in type.Methods)
                        if (DefaultBody(m)) methods++;
                // Completeness so every concrete type JIT-loads (else a survived game method referencing it
                // throws TypeLoadException "method ... does not have an implementation"):
                //   (a) repair explicit-interface-impl methods whose MethodImpl link Il2CppDumper dropped, and
                //   (b) synthesize any interface/abstract slot still missing.
                // Snapshot first — these add methods to the types they visit.
                foreach (var type in AllTypes(module).ToList())
                {
                    RepairExplicitOverrides(type, module);
                    EnsureConcreteImplementations(type, module);
                }
                // Constants typed by enums from OTHER (possibly skipped/failed) assemblies
                // make Module.Write throw; they're compile-time-inlined so drop them.
                DllPatcher.StripUnresolvableConstants(module);
                // Write via memory, then atomically to disk — Module.Write(path) truncates
                // the file BEFORE serializing, so a mid-write throw used to leave a 0-byte
                // facade that poisoned the resolver for every later startup.
                var buf = new MemoryStream();
                module.Write(buf);
                File.WriteAllBytes(Path.Combine(outDir, name + ".dll"), buf.ToArray());
                asm++;
            }
            catch (Exception e)
            {
                Console.WriteLine($"  skip {name}: {e.Message}");
                var stale = Path.Combine(outDir, name + ".dll");   // never leave a 0-byte stump
                try { if (File.Exists(stale) && new FileInfo(stale).Length == 0) File.Delete(stale); } catch { }
            }
        }
        Console.WriteLine($"  generated {asm} facade assemblies ({methods} method bodies -> default) in {outDir}");
    }

    // Diagnostic: does this assembly DEFINE the type (TypeDef), and if so what is it? Also lists any
    // ExportedTypes (type forwards). Helps diagnose "Could not load type X from assembly Y" — Y may only
    // reference X (TypeRef), with the real TypeDef in a different DummyDll.
    public static void InspectType(string dllPath, string simpleName)
    {
        var module = ModuleDefinition.ReadModule(dllPath, new ReaderParameters { ReadWrite = false, InMemory = true });
        Console.WriteLine($"=== INSPECT {Path.GetFileName(dllPath)} for type name '{simpleName}' ===");
        bool any = false;
        foreach (var t in AllTypes(module))
            if (t.Name == simpleName || t.FullName == simpleName)
            {
                any = true;
                Console.WriteLine($"  TypeDef: {t.FullName}  (enum={t.IsEnum}, valuetype={t.IsValueType}, base={t.BaseType?.FullName}, fields={t.Fields.Count}, methods={t.Methods.Count})");
            }
        if (!any) Console.WriteLine("  no TypeDef with that name");
        foreach (var et in module.ExportedTypes)
            if (et.Name == simpleName || et.FullName == simpleName)
                Console.WriteLine($"  ExportedType (forward): {et.FullName} -> scope {et.Scope?.Name}");
        // Also any TypeRef mentioning the name (so we see the assembly it's expected to live in)
        foreach (var tr in module.GetTypeReferences())
            if (tr.Name == simpleName || tr.FullName == simpleName)
                Console.WriteLine($"  TypeRef: {tr.FullName} -> scope {tr.Scope?.Name}");
    }

    // Diagnostic: dump a type's base, interfaces, and every method's loader-relevant flags — to see why a
    // concrete type fails to JIT-load ("method ... does not have an implementation").
    public static void InspectMethods(string dllPath, string simpleName, string filter = "")
    {
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(Path.GetDirectoryName(dllPath));
        resolver.ResolveFailure += (s, r) => AssemblyDefinition.CreateAssembly(new AssemblyNameDefinition(r.Name, r.Version ?? new Version(0, 0)), r.Name, ModuleKind.Dll);
        var module = ModuleDefinition.ReadModule(dllPath, new ReaderParameters { ReadWrite = false, InMemory = true, AssemblyResolver = resolver });
        var t = AllTypes(module).FirstOrDefault(x => x.Name == simpleName || x.FullName == simpleName);
        if (t == null) { Console.WriteLine($"  type {simpleName} not found in {Path.GetFileName(dllPath)}"); return; }
        Console.WriteLine($"=== {t.FullName} (abstract={t.IsAbstract}, base={t.BaseType?.FullName}) ===");
        Console.WriteLine($"  interfaces: {string.Join(", ", t.Interfaces.Select(i => i.InterfaceType.FullName))}");
        for (var c = t; c != null; c = SafeResolve(c.BaseType))
            foreach (var m in c.Methods)
                if ((filter == "" || m.Name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0))
                    Console.WriteLine($"  {(c == t ? "*" : c.Name + ".")}{m.Name}  abstract={m.IsAbstract} internalcall={m.IsInternalCall} pinvoke={m.IsPInvokeImpl} hasBody={m.HasBody} overrides={m.Overrides.Count}");
    }

    // Diagnostic: dump a method's IL with offsets (to locate a runtime NRE by its +IL_xxxx offset).
    // typeName may be a nested compiler-generated state machine like "<Execute>d__52".
    public static void DumpMethodIL(string dllPath, string typeName, string methodName, int aroundHex = -1)
    {
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(Path.GetDirectoryName(dllPath));
        var module = ModuleDefinition.ReadModule(dllPath, new ReaderParameters { ReadWrite = false, InMemory = true });
        var t = AllTypes(module).FirstOrDefault(x => x.Name == typeName || x.FullName == typeName);
        if (t == null) { Console.WriteLine($"  type {typeName} not found"); return; }
        var m = t.Methods.FirstOrDefault(x => x.Name == methodName);
        if (m == null || !m.HasBody) { Console.WriteLine($"  method {methodName} not found / no body"); return; }
        Console.WriteLine($"=== IL {t.FullName}.{m.Name} ({m.Body.Instructions.Count} instrs) ===");
        foreach (var ins in m.Body.Instructions)
        {
            if (aroundHex >= 0 && Math.Abs(ins.Offset - aroundHex) > 48) continue;
            var mark = (aroundHex >= 0 && ins.Offset == aroundHex) ? "  <<< NRE" : "";
            Console.WriteLine($"  IL_{ins.Offset:X4}: {ins.OpCode} {Operand(ins.Operand)}{mark}");
        }
    }
    static string Operand(object? o) => o switch
    {
        null => "",
        MethodReference mr => mr.FullName,
        FieldReference fr => fr.FullName,
        TypeReference tr => tr.FullName,
        Instruction ins => $"IL_{ins.Offset:X4}",
        string s => $"\"{s}\"",
        _ => o.ToString() ?? ""
    };

    // Diagnostic: list a type's static fields (name + type) — to find the real backing field for a config
    // list when the guessed name reports "STATIC NOT FOUND".
    public static void ListStaticFields(string dllPath, string typeName, string filter = "")
    {
        var module = ModuleDefinition.ReadModule(dllPath, new ReaderParameters { ReadWrite = false, InMemory = true });
        var t = AllTypes(module).FirstOrDefault(x => x.Name == typeName || x.FullName == typeName);
        if (t == null) { Console.WriteLine($"  type {typeName} not found"); return; }
        Console.WriteLine($"=== static fields of {t.FullName} (filter='{filter}') ===");
        foreach (var f in t.Fields.Where(f => f.IsStatic && (filter == "" || f.Name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0)))
            Console.WriteLine($"  {f.Name}  : {f.FieldType.Name}");
    }

    // Emit a C# facade stub for ONE type (found in the Il2CppDumper DummyDll), with all public members
    // returning default — used by the facade-gap auto-repair (facade_doctor.py) to fill a "Could not load
    // type X" gap automatically. Prints the C# to stdout (the caller appends it to the facade source).
    public static void EmitFacadeStub(string dummyDir, string typeFullName)
    {
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(dummyDir);
        resolver.ResolveFailure += (s, r) => AssemblyDefinition.CreateAssembly(new AssemblyNameDefinition(r.Name, r.Version ?? new Version(0, 0)), r.Name, ModuleKind.Dll);
        TypeDefinition? td = null;
        foreach (var dll in Directory.GetFiles(dummyDir, "*.dll"))
        {
            try { var m = ModuleDefinition.ReadModule(dll, new ReaderParameters { ReadWrite = false, InMemory = true, AssemblyResolver = resolver }); td = AllTypes(m).FirstOrDefault(t => t.FullName.Replace("/", ".") == typeFullName || t.FullName == typeFullName); }
            catch { }
            if (td != null) break;
        }
        if (td == null) { Console.WriteLine($"// FACADE-STUB NOTFOUND {typeFullName}"); return; }
        if (td.HasGenericParameters || td.IsInterface) { Console.WriteLine($"// FACADE-STUB SKIP {typeFullName} (generic/interface)"); return; }
        var ns = td.Namespace; var name = td.Name;
        var sb = new System.Text.StringBuilder();
        sb.AppendLine($"// auto-added by facade_doctor (facade-gap repair)");
        if (!string.IsNullOrEmpty(ns)) sb.AppendLine($"namespace {ns} {{");
        var kind = td.IsValueType ? "struct" : "class";
        sb.AppendLine($"    public {kind} {name} {{");
        foreach (var f in td.Fields.Where(f => f.IsPublic && !f.IsLiteral))
            sb.AppendLine($"        public {(f.IsStatic ? "static " : "")}{Cs(f.FieldType)} {f.Name};");
        var seen = new System.Collections.Generic.HashSet<string>();
        foreach (var me in td.Methods.Where(x => x.IsPublic && !x.IsConstructor && !x.HasGenericParameters && !x.Name.StartsWith("op_") && x.Name != "Finalize"))
        {
            if (me.Parameters.Any(p => p.ParameterType.ContainsGenericParameter || p.ParameterType.IsByReference)) continue;
            var ps = string.Join(", ", me.Parameters.Select((p, i) => $"{Cs(p.ParameterType)} a{i}"));
            var sig = $"{me.Name}({ps})"; if (!seen.Add(sig)) continue;
            var ret = me.ReturnType.FullName == "System.Void" ? "void" : Cs(me.ReturnType);
            var body = ret == "void" ? "{ }" : "=> default;";
            sb.AppendLine($"        public {(me.IsStatic ? "static " : "")}{ret} {me.Name}({ps}) {body}");
        }
        sb.AppendLine("    }");
        if (!string.IsNullOrEmpty(ns)) sb.AppendLine("}");
        Console.WriteLine(sb.ToString());
    }
    // Cecil TypeReference -> a C# type name the facade compiler accepts (best-effort; primitives mapped).
    static string Cs(TypeReference t)
    {
        if (t is ArrayType at) return Cs(at.ElementType) + "[]";
        if (t is GenericInstanceType git) return git.ElementType.Name.Split('`')[0] + "<" + string.Join(", ", git.GenericArguments.Select(Cs)) + ">";
        switch (t.FullName)
        {
            case "System.Void": return "void"; case "System.Single": return "float"; case "System.Double": return "double";
            case "System.Int32": return "int"; case "System.Int64": return "long"; case "System.UInt32": return "uint"; case "System.UInt64": return "ulong";
            case "System.Boolean": return "bool"; case "System.String": return "string"; case "System.Object": return "object";
            case "System.Byte": return "byte"; case "System.SByte": return "sbyte"; case "System.Int16": return "short"; case "System.UInt16": return "ushort"; case "System.Char": return "char";
        }
        return (string.IsNullOrEmpty(t.Namespace) ? "" : t.Namespace + ".") + t.Name.Replace("/", ".");
    }

    static System.Collections.Generic.IEnumerable<TypeDefinition> AllTypes(ModuleDefinition m)
    {
        foreach (var t in m.Types) { yield return t; foreach (var n in Nested(t)) yield return n; }
    }
    static System.Collections.Generic.IEnumerable<TypeDefinition> Nested(TypeDefinition t)
    {
        foreach (var n in t.NestedTypes) { yield return n; foreach (var nn in Nested(n)) yield return nn; }
    }

    // Replace a method body with: (ctor) call base parameterless ctor then ret; (else) return default.
    static bool DefaultBody(MethodDefinition m)
    {
        // Skip only IsRuntime (delegate Invoke/BeginInvoke etc. — the runtime MUST provide these; an IL body
        // would corrupt them) and interface declarations. Everything else is FORCED to a concrete IL body —
        // including methods Il2CppDumper marks abstract, extern InternalCall, or PInvoke. This matters: Unity
        // engine accessors like `Component.get_transform` / `Image.get_transform` are [MethodImpl(InternalCall)]
        // with no IL; left as-is, a CONCRETE type declaring one fails to JIT-load ("method ... does not have an
        // implementation") the instant any survived game method references it. Clearing the impl flags + giving
        // a default body makes every facade type fully loadable.
        if (m.IsRuntime || m.DeclaringType.IsInterface) return false;
        bool needBody = m.IsAbstract || m.IsInternalCall || m.IsPInvokeImpl || !m.HasBody;
        m.IsAbstract = false;
        m.IsInternalCall = false;
        if (m.IsPInvokeImpl) { m.IsPInvokeImpl = false; m.PInvokeInfo = null; }
        m.ImplAttributes = MethodImplAttributes.IL | MethodImplAttributes.Managed;   // ensure an IL body is expected
        if (needBody) m.Body = new MethodBody(m);
        m.Body.Instructions.Clear();
        m.Body.ExceptionHandlers.Clear();
        m.Body.Variables.Clear();
        var il = m.Body.GetILProcessor();

        if (m.IsConstructor && !m.IsStatic)
        {
            // Chain to a parameterless base ctor so the instance is valid IL. If none exists, just ret
            // (CoreCLR is lenient for loaded assemblies; most facade bases are Object/MonoBehaviour).
            var baseType = m.DeclaringType.BaseType;
            var baseCtor = baseType != null ? ResolveParameterlessCtor(baseType) : null;
            if (baseCtor != null)
            {
                il.Append(il.Create(OpCodes.Ldarg_0));
                il.Append(il.Create(OpCodes.Call, m.Module.ImportReference(baseCtor)));
            }
            il.Append(il.Create(OpCodes.Ret));
            return true;
        }

        FillDefaultReturn(m);
        return true;
    }

    // Fill m's (already-cleared) body with a default-return: void -> ret; reference -> NON-NULL inert (the
    // game dereferences facade results, so null would NRE the caller -> silently wrong combat); value/generic
    // -> default(T). Shared by DefaultBody (declared methods) and synthesized inherited-slot impls.
    static void FillDefaultReturn(MethodDefinition m)
    {
        var il = m.Body.GetILProcessor();
        var ret = m.ReturnType;
        if (ret.FullName == "System.Void") { il.Append(il.Create(OpCodes.Ret)); return; }
        if (!ret.IsValueType && !ret.IsGenericParameter && !ret.IsPointer && !ret.IsByReference)
        {
            try { if (EmitNonNullRef(m, il, ret)) return; }
            catch { m.Body.Instructions.Clear(); m.Body.Variables.Clear(); }   // fall back to default(T)
        }
        var v = new VariableDefinition(m.Module.ImportReference(ret));
        m.Body.Variables.Add(v);
        m.Body.InitLocals = true;
        il.Append(il.Create(OpCodes.Ldloca_S, v));
        il.Append(il.Create(OpCodes.Initobj, m.Module.ImportReference(ret)));
        il.Append(il.Create(OpCodes.Ldloc, v));
        il.Append(il.Create(OpCodes.Ret));
    }

    // ── INHERITED-SLOT COMPLETENESS ────────────────────────────────────────────────────────────────────
    // A CONCRETE type still fails to JIT-load ("Method X in type Y does not have an implementation") if it
    // inherits an abstract/interface method it never declares — Il2CppDumper omits the implicit override
    // (e.g. UnityEngine.UI.Image leaves an interface get_transform unimplemented). The instant any survived
    // game method references such a type, the JIT throws TypeLoadException. So for every concrete type, walk
    // its interface set + abstract base chain and synthesize a default-body impl for each non-generic slot it
    // doesn't already implement. Purely additive (loadable types already satisfy every slot -> nothing added).
    // Il2CppDumper emits explicit-interface-impl methods by NAME ("Namespace.IFace.Method") but frequently
    // DROPS the MethodImpl (.Overrides) link that actually binds the method to the interface slot. Without it
    // the runtime treats the method as a plain oddly-named member and the interface slot stays unimplemented
    // -> any concrete type in that hierarchy fails to JIT-load. Re-derive the link from the dotted name.
    static void RepairExplicitOverrides(TypeDefinition t, ModuleDefinition module)
    {
        List<MethodDefinition> methods;
        try { methods = t.Methods.ToList(); } catch { return; }
        foreach (var m in methods)
        {
            try
            {
                if (m.IsConstructor || m.Overrides.Count > 0) continue;
                int dot = m.Name.LastIndexOf('.');
                if (dot <= 0) continue;                       // not an explicit-impl-style name
                var ifaceName = m.Name.Substring(0, dot);
                var simple = m.Name.Substring(dot + 1);
                foreach (var im in InterfaceClosureMethods(t))
                {
                    if (im.Name != simple || im.Parameters.Count != m.Parameters.Count) continue;
                    if ((im.DeclaringType.FullName ?? "") != ifaceName) continue;
                    m.Overrides.Add(module.ImportReference(im));
                    m.IsAbstract = false;
                    m.Attributes |= MethodAttributes.Virtual | MethodAttributes.Final | MethodAttributes.NewSlot | MethodAttributes.HideBySig;
                    if (!m.HasBody) { m.Body = new MethodBody(m); FillDefaultReturn(m); }
                    break;
                }
            }
            catch { /* leave this method as-is */ }
        }
    }

    static void EnsureConcreteImplementations(TypeDefinition t, ModuleDefinition module)
    {
        if (t.IsInterface || t.IsAbstract || t.HasGenericParameters) return;
        HashSet<string> declared;
        try { declared = new HashSet<string>(t.Methods.Select(MethodKey)); } catch { return; }
        // (1) interface methods (recursive over the closure) then (2) abstract base methods. Each slot is
        // guarded: a single unresolvable/odd slot must never abort the type or the assembly (coverage > all).
        void TryFill(System.Collections.Generic.IEnumerable<MethodDefinition> reqs, bool iface)
        {
            List<MethodDefinition> list;
            try { list = reqs.ToList(); } catch { return; }
            foreach (var r in list)
            {
                try
                {
                    if (Untranslatable(r)) continue;
                    var key = MethodKey(r);
                    if (declared.Contains(key) || HasConcreteImpl(t, r)) continue;
                    t.Methods.Add(Synthesize(module, r, iface)); declared.Add(key);
                }
                catch { /* skip this slot; type stays as-is (no worse than before) */ }
            }
        }
        TryFill(InterfaceClosureMethods(t), true);
        TryFill(AbstractBaseMethods(t), false);
    }

    static MethodDefinition Synthesize(ModuleDefinition module, MethodReference src, bool isInterfaceImpl)
    {
        var attrs = MethodAttributes.Public | MethodAttributes.Virtual | MethodAttributes.HideBySig
                  | (isInterfaceImpl ? MethodAttributes.NewSlot | MethodAttributes.Final : MethodAttributes.ReuseSlot);
        var md = new MethodDefinition(src.Name, attrs, module.ImportReference(src.ReturnType));
        foreach (var p in src.Parameters)
            md.Parameters.Add(new ParameterDefinition(module.ImportReference(p.ParameterType)));
        md.Body = new MethodBody(md);
        FillDefaultReturn(md);
        if (isInterfaceImpl) md.Overrides.Add(module.ImportReference(src));   // explicit slot mapping
        return md;
    }

    // A method we can't faithfully re-declare (generic shape, by-ref/pointer params, special names we don't
    // synthesize). Leaving these is no regression — the type was already unloadable; we just don't fix it yet.
    static bool Untranslatable(MethodReference m) =>
        m.HasGenericParameters || m.ReturnType.ContainsGenericParameter || m.ReturnType.IsByReference || m.ReturnType.IsPointer
        || m.Parameters.Any(p => p.ParameterType.ContainsGenericParameter || p.ParameterType.IsByReference || p.ParameterType.IsPointer)
        || (m.DeclaringType?.IsGenericInstance ?? false);

    static string MethodKey(MethodReference m) =>
        m.Name + "(" + string.Join(",", m.Parameters.Select(p => p.ParameterType.FullName)) + ")";

    // All methods of every interface in t's transitive interface closure (incl. interfaces of base classes
    // and interface inheritance), instance methods only.
    static System.Collections.Generic.IEnumerable<MethodDefinition> InterfaceClosureMethods(TypeDefinition t)
    {
        var seen = new HashSet<string>();
        var ifaces = new System.Collections.Generic.List<TypeDefinition>();
        void AddIface(TypeReference ir)
        {
            var d = SafeResolve(ir); if (d == null || !seen.Add(d.FullName)) return;
            ifaces.Add(d);
            foreach (var sub in d.Interfaces) AddIface(sub.InterfaceType);
        }
        for (var c = t; c != null; c = SafeResolve(c.BaseType))
            foreach (var i in c.Interfaces) AddIface(i.InterfaceType);
        foreach (var i in ifaces)
            foreach (var m in i.Methods)
                if (!m.IsStatic) yield return m;
    }

    static System.Collections.Generic.IEnumerable<MethodDefinition> AbstractBaseMethods(TypeDefinition t)
    {
        for (var b = SafeResolve(t.BaseType); b != null; b = SafeResolve(b.BaseType))
            foreach (var m in b.Methods)
                if (m.IsAbstract && !m.IsStatic) yield return m;
    }

    // Does t (or a base class) already declare a concrete (non-abstract) method matching req's name+params?
    static bool HasConcreteImpl(TypeDefinition t, MethodReference req)
    {
        var key = MethodKey(req);
        for (var c = t; c != null; c = SafeResolve(c.BaseType))
            if (c.Methods.Any(m => !m.IsAbstract && MethodKey(m) == key)) return true;
        return false;
    }

    static TypeDefinition? SafeResolve(TypeReference? tr) { try { return tr?.Resolve(); } catch { return null; } }

    // Emit IL pushing a NON-NULL inert instance of reference type `ret` and returning it. Returns false
    // (emitting nothing) when no safe non-null instance exists — interfaces, abstract types, or types that
    // can't be resolved — leaving the caller to fall back to default(T)/null (no worse than before).
    static bool EmitNonNullRef(MethodDefinition m, ILProcessor il, TypeReference ret)
    {
        var module = m.Module;
        if (ret.FullName == "System.String")
        { il.Append(il.Create(OpCodes.Ldstr, "")); il.Append(il.Create(OpCodes.Ret)); return true; }
        if (ret is ArrayType at)   // new T[0]
        {
            il.Append(il.Create(OpCodes.Ldc_I4_0));
            il.Append(il.Create(OpCodes.Newarr, module.ImportReference(at.ElementType)));
            il.Append(il.Create(OpCodes.Ret));
            return true;
        }
        TypeDefinition? def = ret.Resolve();
        if (def == null || def.IsInterface || def.IsAbstract) return false;   // can't instantiate -> null
        // Parameterless ctor -> newobj (List<Foo>(), most concrete classes incl. protobuf config messages).
        var ctor = def.Methods.FirstOrDefault(c => c.IsConstructor && !c.IsStatic && c.Parameters.Count == 0);
        if (ctor != null)
        {
            MethodReference ctorRef = ret.IsGenericInstance
                ? new MethodReference(".ctor", module.TypeSystem.Void, module.ImportReference(ret)) { HasThis = true }
                : module.ImportReference(ctor);
            il.Append(il.Create(OpCodes.Newobj, ctorRef));
            il.Append(il.Create(OpCodes.Ret));
            return true;
        }
        // Concrete, no parameterless ctor -> allocate WITHOUT running a ctor (T is concrete & non-abstract,
        // so GetUninitializedObject is valid). Inert: the object exists, fields are zero/default.
        var gtfh = module.ImportReference(typeof(Type).GetMethod("GetTypeFromHandle", new[] { typeof(RuntimeTypeHandle) }));
        var gu = module.ImportReference(typeof(System.Runtime.CompilerServices.RuntimeHelpers).GetMethod("GetUninitializedObject", new[] { typeof(Type) }));
        il.Append(il.Create(OpCodes.Ldtoken, module.ImportReference(ret)));
        il.Append(il.Create(OpCodes.Call, gtfh));
        il.Append(il.Create(OpCodes.Call, gu));
        il.Append(il.Create(OpCodes.Castclass, module.ImportReference(ret)));
        il.Append(il.Create(OpCodes.Ret));
        return true;
    }

    static MethodReference? ResolveParameterlessCtor(TypeReference baseType)
    {
        try
        {
            var def = baseType.Resolve();
            return def?.Methods.FirstOrDefault(c => c.IsConstructor && !c.IsStatic && c.Parameters.Count == 0);
        }
        catch { return null; }
    }
}
