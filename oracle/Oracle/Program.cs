// Yi Xian Oracle — headless battle simulator (native CoreCLR run path).
//
// Loads the real game DLL (Cecil-patched to nop visual methods) into CoreCLR via NativeRunner, which
// JIT-compiles the game's own IL to native machine code and drives combat by reflection — bit-exact by
// construction and ~30x faster than the old ILRuntime interpreter. The legacy ILRuntime execution path
// (interpreter AppDomain + transcribed turn loop) was removed 2026-06-03; native is the only path.
//
// Dispatch (handled inside NativeRunner.Run, by args):
//   --records-dir <dir> [--shard <i> <n>] [--results-out <path>]   full-suite sweep -> _results.json
//   --run-fixture <path.json>                                       one fixture -> {"engine":"oracle",...}
//   (default)                                                       sample_battle probe (faults + timing)

using System;
using System.IO;
using System.Linq;
using YiXianOracle;

class Program
{
    static void Main(string[] args)
    {
        Console.WriteLine("Yi Xian Oracle (native)");
        Console.WriteLine("=======================\n");

        // Standalone layout (rewired from the original monorepo): everything lives under <oracle>/.
        // The bin dir is <oracle>/Oracle/bin/Release/net8.0, so oracle root is 4 levels up. ORACLE_HOME
        // overrides it (for the packaged app / warm pool launched from a different cwd).
        var projectRoot = Environment.GetEnvironmentVariable("ORACLE_HOME")
            ?? Path.GetFullPath(Path.Combine(
                AppDomain.CurrentDomain.BaseDirectory, "..", "..", "..", ".."));
        var dllPath = Path.Combine(projectRoot, "data", "extracted", "DarkSun.HotUpdate.dll");
        var facadesDir = Path.Combine(projectRoot, "UnityStubs", "bin", "facades");
        var configsDir = Path.Combine(projectRoot, "data", "extracted", "configs");

        // --store <dir>: pin the GAME-VERSION artifacts (DLL + configs) from a snapshot (data/versions/<V>/),
        // instead of the live data/extracted scratch — so a replay recorded under version V runs against V's
        // gameplay code. It does NOT pin facades-gen or auto_patch.json: those are RUNNER-DERIVED (regenerated
        // by FacadeGen/the doctor, which the consolidation agent evolves continuously), so a snapshot copy goes
        // stale against the current DllPatcher and breaks combat. Facades-gen + auto_patch always come LIVE.
        int storeIdx = System.Array.IndexOf(args, "--store");
        if (storeIdx >= 0 && storeIdx + 1 < args.Length)
        {
            var store = Path.GetFullPath(args[storeIdx + 1]);
            dllPath = Path.Combine(store, "DarkSun.HotUpdate.dll");
            configsDir = Path.Combine(store, "configs");
            Console.WriteLine($"  [--store] game artifacts pinned to {store} (facades-gen + auto_patch stay live)");
        }

        if (!File.Exists(dllPath)) { Console.WriteLine($"DLL not found: {dllPath}"); return; }

        // --ildump <Type> <Method> [hexOffset] : Cecil IL disassembly of a method (debug).
        if (args.Contains("--ildump"))
        {
            int i = System.Array.IndexOf(args, "--ildump");
            int around = (i + 3 < args.Length && int.TryParse(args[i + 3], System.Globalization.NumberStyles.HexNumber, null, out var h)) ? h : -1;
            DllPatcher.DumpMethodIL(dllPath, args[i + 1], args[i + 2], around);
            Console.Out.Flush(); Environment.Exit(0);
        }

        // --gen-facades : regenerate the complete facade assemblies from Il2CppDumper's DummyDll. Every
        // referenced external type becomes a runnable facade whose methods return NON-NULL inert values
        // (FacadeGen.DefaultBody), so headless game code never NREs on a facade result. Re-run per game update.
        if (args.Contains("--gen-facades"))
        {
            var dummyDir = Path.Combine(projectRoot, "tools", "Il2CppDumper", "v6.7.46", "DummyDll");
            var outDir = Path.Combine(projectRoot, "UnityStubs", "bin", "facades-gen");
            int oi = System.Array.IndexOf(args, "--out");   // --out <dir>: generate to a side dir (safe testing)
            if (oi >= 0 && oi + 1 < args.Length) outDir = args[oi + 1];
            if (!Directory.Exists(dummyDir)) { Console.WriteLine($"DummyDll not found: {dummyDir}"); Environment.Exit(1); }
            FacadeGen.Generate(dummyDir, outDir);
            Console.Out.Flush(); Environment.Exit(0);
        }

        // --emit-facade-stub <TypeFullName> : print a C# facade stub for a type (from DummyDll), for the
        // facade-gap auto-repair (facade_doctor.py) to append to the facade source.
        // --inspect-methods <dll> <TypeName> [filter] : list a type's base/interfaces/method flags.
        if (args.Contains("--inspect-methods"))
        {
            int i = System.Array.IndexOf(args, "--inspect-methods");
            FacadeGen.InspectMethods(args[i + 1], args[i + 2], i + 3 < args.Length ? args[i + 3] : "");
            Console.Out.Flush(); Environment.Exit(0);
        }

        if (args.Contains("--emit-facade-stub"))
        {
            int i = System.Array.IndexOf(args, "--emit-facade-stub");
            var dummyDir = Path.Combine(projectRoot, "tools", "Il2CppDumper", "v6.7.46", "DummyDll");
            FacadeGen.EmitFacadeStub(dummyDir, args[i + 1]);
            Console.Out.Flush(); Environment.Exit(0);
        }

        // --gen-state-index [--out <path>] : static-analyze the game's effect callgraph and emit the closed set
        // of GAMEPLAY reads off VISUAL MIRROR objects — the complete "core state to emulate" index. The general
        // solution to the inert-visual bug class (vs discovering each via a parity failure).
        if (args.Contains("--gen-state-index"))
        {
            var outPath = Path.Combine(projectRoot, "data", "game", "oracle_audit", "state_index.json");
            int oi = System.Array.IndexOf(args, "--out");
            if (oi >= 0 && oi + 1 < args.Length) outPath = args[oi + 1];
            StateIndexGen.Generate(dllPath, outPath);
            Console.Out.Flush(); Environment.Exit(0);
        }

        // --classify-visual [handfix_list.json] : statically label every method GAMEPLAY vs PURE-VISUAL by reading
        // its IL (transitive). Cross-checks the hand-nop list: which nops are GAMEPLAY (wrong — drop gameplay).
        if (args.Contains("--classify-visual"))
        {
            int i = System.Array.IndexOf(args, "--classify-visual");
            string? hf = (i + 1 < args.Length && !args[i + 1].StartsWith("--")) ? args[i + 1] : null;
            int ei = System.Array.IndexOf(args, "--emit-patch");
            string? emit = (ei >= 0 && ei + 1 < args.Length) ? args[ei + 1] : null;
            VisualClassifier.Classify(dllPath, hf, emit);
            Console.Out.Flush(); Environment.Exit(0);
        }

        // NativeRunner owns facade resolution, DLL+config loading, and the arg dispatch above.
        NativeRunner.Run(args, dllPath, facadesDir, configsDir);
        Console.Out.Flush();
        Environment.Exit(0);
    }
}
