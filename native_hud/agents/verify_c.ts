// verify_c.ts — Path C spike: can a SELF-WRITTEN assembly be loaded into the
// game's live ILRuntime AppDomain and (Stage 2) reference the game's own
// hot-update types? Reuses the AppDomain handle pattern from autoplay/inject/actions.ts.
import "frida-il2cpp-bridge";

function raw(x: any): string { return x && x.content != null ? x.content : ("" + x); }

function findClassFull(full: string, simple: string): Il2Cpp.Class | null {
  for (const asm of Il2Cpp.domain.assemblies) {
    try { const k = asm.image.class(full); if (k) return k; } catch (_) {}
  }
  for (const asm of Il2Cpp.domain.assemblies) {
    try { for (const c of asm.image.classes) if (c.name === simple) return c; } catch (_) {}
  }
  return null;
}

let AD: any, ADCLS: Il2Cpp.Class, INVOKE: any, EMPTY: any;
function getAD(): any {
  if (!AD) {
    ADCLS = findClassFull("ILRuntime.Runtime.Enviorment.AppDomain", "AppDomain")!;
    if (!ADCLS) throw new Error("AppDomain class not found");
    const insts = Il2Cpp.gc.choose(ADCLS);
    if (!insts.length) throw new Error("no live AppDomain instance");
    AD = insts[0];
    INVOKE = AD.method("Invoke", 3);                                  // Invoke(IMethod, object, object[])
    EMPTY = Il2Cpp.array(Il2Cpp.corlib.class("System.Object"), []);
  }
  return AD;
}

// enumerate LoadAssembly overloads; pick the one taking a single System.IO.Stream
function findLoadAssemblyStream(): any {
  let best: any = null;
  for (const m of ADCLS.methods) {
    if (m.name !== "LoadAssembly") continue;
    const ps = m.parameterCount;
    const tn = ps >= 1 ? raw(m.parameters[0].type.name) : "";
    if (ps === 1 && /Stream/.test(tn)) return m;
    if (ps === 1 && !best) best = m;     // fallback: any 1-arg
  }
  return best;
}

function bytesToIl2cppByteArray(buf: ArrayBuffer): any {
  const u8 = new Uint8Array(buf);
  const arr: any = Il2Cpp.array(Il2Cpp.corlib.class("System.Byte"), u8.length);
  for (let i = 0; i < u8.length; i++) arr.set(i, u8[i]);
  return arr;
}

function memoryStream(arr: any): any {
  const msCls = Il2Cpp.corlib.class("System.IO.MemoryStream");
  const ms: any = msCls.alloc();
  // instance ctor, disambiguated by param type (NOT MemoryStream(int capacity))
  ms.method(".ctor").overload("System.Byte[]").invoke(arr);
  return ms;
}

// walk AppDomain.mapType InnerDictionary for an interpreted IType by full name
function getIType(name: string): any {
  const tsd: any = AD.field("mapType").value;
  const dict: any = tsd.method("get_InnerDictionary").invoke();
  const entries: any = dict.field("entries").value;
  const count: number = dict.field("count").value;
  for (let i = 0; i < count; i++) {
    try {
      const e: any = entries.get(i);
      const key: any = e.field("key").value;
      if (key != null && raw(key) === name) return e.field("value").value;
    } catch (_) {}
  }
  return null;
}

function getMethod(typeName: string, methodName: string, pc: number): any {
  const it = getIType(typeName);
  if (!it) return { it: false, m: null };
  const ms: any = it.method("GetMethods").invoke();
  const n = ms.method("get_Count").invoke();
  for (let i = 0; i < n; i++) {
    const m: any = ms.method("get_Item").invoke(i);
    if (raw(m.method("get_Name").invoke()) !== methodName) continue;
    try { if (("" + m.method("get_ParameterCount").invoke()) !== ("" + pc)) continue; } catch (_) {}
    return { it: true, m };
  }
  return { it: true, m: null };
}

rpc.exports = {
  // diagnostics: confirm AppDomain reachable + show LoadAssembly overloads
  info(): any {
    return Il2Cpp.perform(() => {
      try {
        getAD();
        const overloads: string[] = [];
        for (const m of ADCLS.methods) {
          if (m.name !== "LoadAssembly") continue;
          overloads.push(m.parameters.map((p: any) => raw(p.type.name)).join(", ") || "()");
        }
        const la = findLoadAssemblyStream();
        return { ok: true, appdomain: !AD.isNull(), loadAssemblyOverloads: overloads,
                 pickedStreamOverload: la ? la.parameters.map((p: any) => raw(p.type.name)).join(",") : null };
      } catch (e) { return { ok: false, err: "" + e }; }
    });
  },

  // load `dll` (ArrayBuffer) into the live AppDomain, then invoke no-arg static
  // `typeName.methodName` and return its result. Proves C end-to-end.
  probe(typeName: string, methodName: string, dll: ArrayBuffer): any {
    return Il2Cpp.perform(() => {
      try {
        getAD();
        // before: type should NOT exist yet
        const before = !!getIType(typeName);
        const arr = bytesToIl2cppByteArray(dll);
        const ms = memoryStream(arr);
        AD.method("LoadAssembly").overload("System.IO.Stream").invoke(ms);   // ← instance call on AppDomain
        const after = !!getIType(typeName);
        const gm = getMethod(typeName, methodName, 0);
        if (!gm.it) return { ok: false, stage: "resolve-type", err: `type ${typeName} not in AppDomain after load`, before, after };
        if (!gm.m)  return { ok: false, stage: "resolve-method", err: `method ${methodName} not found`, before, after };
        const res = INVOKE.invoke(gm.m, NULL, EMPTY);                 // static → instance=null
        return { ok: true, before, after, result: raw(res) };
      } catch (e) { return { ok: false, err: "" + e, stack: (e as any).stack }; }
    });
  },
};

console.log("[verify_c] agent ready (rpc: info / probe)");
