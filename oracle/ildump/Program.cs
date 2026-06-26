// ildump — dump a method's IL (with offsets) or list a type's members, from the game DLL.
// Standalone Cecil tool; reuses the deleted FacadeGen diagnostics. The faults in the Oracle sweep name
// "<Type>.<Method>+IL_xxxx", so this locates the exact instruction that NRE'd.
//
//   dotnet run --project tools/game-oracle/ildump -- il   "<Type>" "<Method>" [hexOffset]
//   dotnet run --project tools/game-oracle/ildump -- type  "<TypeNameOrFragment>"
//   dotnet run --project tools/game-oracle/ildump -- fields "<Type>" [nameFilter]
// <Type> may be a nested compiler-gen state machine, e.g. "<Execute>d__52".
using ILRuntime.Mono.Cecil;
using ILRuntime.Mono.Cecil.Cil;

var dll = Environment.GetEnvironmentVariable("ORACLE_DLL")
    ?? Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "..",
        "data", "extracted", "DarkSun.HotUpdate.dll"));
if (!File.Exists(dll)) { Console.WriteLine($"DLL not found: {dll}"); return; }
var module = ModuleDefinition.ReadModule(dll, new ReaderParameters { ReadWrite = false, InMemory = true });

IEnumerable<TypeDefinition> All(ModuleDefinition m)
{ foreach (var t in m.Types) { yield return t; foreach (var n in Nested(t)) yield return n; } }
IEnumerable<TypeDefinition> Nested(TypeDefinition t)
{ foreach (var n in t.NestedTypes) { yield return n; foreach (var nn in Nested(n)) yield return nn; } }

string Op(object? o) => o switch {
    null => "", MethodReference mr => mr.FullName, FieldReference fr => fr.FullName,
    TypeReference tr => tr.FullName, Instruction i => $"IL_{i.Offset:X4}",
    string s => $"\"{s}\"", _ => o.ToString() ?? "" };

var cmd = args.Length > 0 ? args[0] : "";
if (cmd == "il" && args.Length >= 3)
{
    var t = All(module).FirstOrDefault(x => x.Name == args[1] || x.FullName == args[1]);
    if (t == null) { Console.WriteLine($"type {args[1]} not found"); return; }
    var matches = t.Methods.Where(x => x.Name == args[2] && x.HasBody).ToList();
    if (matches.Count == 0) { Console.WriteLine($"method {args[2]} not found / no body"); return; }
    int around = args.Length >= 4 && int.TryParse(args[3], System.Globalization.NumberStyles.HexNumber, null, out var h) ? h : -1;
    foreach (var m in matches)
    {
        var sig = string.Join(",", m.Parameters.Select(p => p.ParameterType.Name));
        Console.WriteLine($"=== IL {t.FullName}.{m.Name}({sig}) : {m.ReturnType.Name}  ({m.Body.Instructions.Count} instrs) ===");
        foreach (var ins in m.Body.Instructions)
        {
            if (around >= 0 && Math.Abs(ins.Offset - around) > 64) continue;
            var mark = around >= 0 && ins.Offset == around ? "   <<< here" : "";
            Console.WriteLine($"  IL_{ins.Offset:X4}: {ins.OpCode,-12} {Op(ins.Operand)}{mark}");
        }
    }
}
else if (cmd == "type" && args.Length >= 2)
{
    foreach (var t in All(module).Where(x => x.Name.Contains(args[1], StringComparison.OrdinalIgnoreCase)
                                          || x.FullName.Contains(args[1], StringComparison.OrdinalIgnoreCase)).Take(30))
        Console.WriteLine($"  {t.FullName}  (base={t.BaseType?.Name}, fields={t.Fields.Count}, methods={t.Methods.Count})");
}
else if (cmd == "fields" && args.Length >= 2)
{
    var t = All(module).FirstOrDefault(x => x.Name == args[1] || x.FullName == args[1]);
    if (t == null) { Console.WriteLine($"type {args[1]} not found"); return; }
    var filt = args.Length >= 3 ? args[2] : "";
    foreach (var f in t.Fields.Where(f => filt == "" || f.Name.Contains(filt, StringComparison.OrdinalIgnoreCase)))
        Console.WriteLine($"  {(f.IsStatic ? "static " : "")}{f.Name} : {f.FieldType.Name}");
}
else if (cmd == "configaudit")
{
    // Which Proto.*Config tables does COMBAT code reference, and is the .dat loaded by the runner?
    // Surfaces unloaded-but-combat-needed configs (null lookups -> NRE / wrong damage). Args:
    //   configaudit <configsDir> <loadedCsv>   (loadedCsv = comma-list of loaded config base names)
    var configsDir = args.Length >= 2 ? args[1] : "";
    var loaded = new HashSet<string>((args.Length >= 3 ? args[2] : "").Split(',', StringSplitOptions.RemoveEmptyEntries), StringComparer.OrdinalIgnoreCase);
    bool IsCombat(TypeDefinition t)
    {
        var n = t.Name; var dn = t.DeclaringType?.Name ?? "";
        bool C(string s) => s is "BattleCharacter" or "BattleExecuter" or "CardActionBase" or "KeYinCardFunctions"
            or "CardFunctions" or "BuffFunctions" || s.StartsWith("Card_") || s.StartsWith("Buff_") || s.EndsWith("Functions");
        return C(n) || C(dn);
    }
    var refs = new Dictionary<string, int>(StringComparer.Ordinal);
    void Bump(TypeReference? tr)
    {
        if (tr == null) return;
        var name = tr.Name; // e.g. CharacterAnimClipConfig, or List`1<..Config>
        var inner = tr.Namespace == "Proto" && name.EndsWith("Config") ? name : null;
        if (inner == null && tr is GenericInstanceType git)
            inner = git.GenericArguments.Select(a => a.Name).FirstOrDefault(a => a.EndsWith("Config"));
        if (inner != null) refs[inner] = refs.GetValueOrDefault(inner) + 1;
    }
    foreach (var t in All(module).Where(IsCombat))
        foreach (var m in t.Methods.Where(m => m.HasBody))
            foreach (var ins in m.Body.Instructions)
            {
                if (ins.Operand is MethodReference mr) Bump(mr.ReturnType);
                else if (ins.Operand is FieldReference fr) Bump(fr.FieldType);
            }
    bool HasDat(string c) => configsDir != "" && File.Exists(Path.Combine(configsDir, c + ".dat"));
    Console.WriteLine("config (referenced by combat code)        refs  .dat  loaded");
    foreach (var (c, n) in refs.OrderByDescending(kv => kv.Value))
    {
        bool dat = HasDat(c), isLoaded = loaded.Contains(c);
        var flag = (dat && !isLoaded) ? "  <-- UNLOADED + has .dat (candidate)" : "";
        Console.WriteLine($"  {c,-42} {n,4}  {(dat ? "yes" : "no "),-4}  {(isLoaded ? "yes" : "NO "),-4}{flag}");
    }
}
else Console.WriteLine("usage: il <Type> <Method> [hexOffset] | type <fragment> | fields <Type> [filter] | configaudit <configsDir> <loadedCsv>");
