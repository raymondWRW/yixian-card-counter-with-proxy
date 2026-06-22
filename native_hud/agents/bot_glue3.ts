// bot_glue2.ts — generic same-domain bot glue. Load any bot assembly, then call
// any `<typeName>.<method>(CardPanel, int...)` by name. Reusable across iterations
// (pass a fresh typeName each time so ILRuntime loads a new assembly identity).
import "frida-il2cpp-bridge";

function raw(x: any): string { return x && x.content != null ? x.content : ("" + x); }
function findClassFull(full: string, simple: string): Il2Cpp.Class | null {
  for (const asm of Il2Cpp.domain.assemblies) { try { const k = asm.image.class(full); if (k) return k; } catch (_) {} }
  for (const asm of Il2Cpp.domain.assemblies) { try { for (const c of asm.image.classes) if (c.name === simple) return c; } catch (_) {} }
  return null;
}

let AD: any, INVOKE: any, ITI: Il2Cpp.Class | null, OBJCLS: Il2Cpp.Class;
function getAD(): any {
  if (!AD) {
    AD = Il2Cpp.gc.choose(findClassFull("ILRuntime.Runtime.Enviorment.AppDomain", "AppDomain")!)[0];
    INVOKE = AD.method("Invoke", 3);
    ITI = findClassFull("ILRuntime.Runtime.Intepreter.ILTypeInstance", "ILTypeInstance");
    OBJCLS = Il2Cpp.corlib.class("System.Object");
  }
  return AD;
}
function getIType(name: string): any {
  const dict: any = (AD.field("mapType").value).method("get_InnerDictionary").invoke();
  const entries: any = dict.field("entries").value, count: number = dict.field("count").value;
  for (let i = 0; i < count; i++) {
    try { const e: any = entries.get(i); const k: any = e.field("key").value;
      if (k != null && raw(k) === name) return e.field("value").value; } catch (_) {}
  }
  return null;
}
function getMethod(typeName: string, methodName: string, pc: number): any {
  const it = getIType(typeName); if (!it) return null;
  const ms: any = it.method("GetMethods").invoke(); const n = ms.method("get_Count").invoke();
  for (let i = 0; i < n; i++) {
    const m: any = ms.method("get_Item").invoke(i);
    if (raw(m.method("get_Name").invoke()) !== methodName) continue;
    try { if (("" + m.method("get_ParameterCount").invoke()) !== ("" + pc)) continue; } catch (_) {}
    return m;
  }
  return null;
}
function boxInt(n: number): any { const o: any = Il2Cpp.corlib.class("System.Int32").alloc(); o.field("m_value").value = n; return o; }
function findCardPanel(): any {
  for (const inst of Il2Cpp.gc.choose(ITI!)) {
    try { if (raw((inst as any).method("get_Type").invoke().method("get_Name").invoke()) === "CardPanel") return inst; } catch (_) {}
  }
  return null;
}
function invokeNamed(typeName: string, method: string, args: any[]): string {
  const m = getMethod(typeName, method, args.length);
  if (!m) throw new Error(`${typeName}.${method}/${args.length} not found`);
  return raw(INVOKE.invoke(m, NULL, Il2Cpp.array(OBJCLS, args)));
}

rpc.exports = {
  loadBot(dll: ArrayBuffer): any {
    return Il2Cpp.perform(() => {
      try {
        getAD();
        const u8 = new Uint8Array(dll);
        const arr: any = Il2Cpp.array(Il2Cpp.corlib.class("System.Byte"), u8.length);
        for (let i = 0; i < u8.length; i++) arr.set(i, u8[i]);
        const ms: any = Il2Cpp.corlib.class("System.IO.MemoryStream").alloc();
        ms.method(".ctor").overload("System.Byte[]").invoke(arr);
        AD.method("LoadAssembly").overload("System.IO.Stream").invoke(ms);
        return { ok: true };
      } catch (e) { return { ok: false, err: "" + e }; }
    });
  },
  // ping a no-arg static (no CardPanel)
  ping(typeName: string): any {
    return Il2Cpp.perform(() => { try { getAD(); return { ok: true, result: invokeNamed(typeName, "Ping", []) }; }
      catch (e) { return { ok: false, err: "" + e }; } });
  },
  // call <typeName>.<method>(CardPanel, ...ints) — heap-scans the live CardPanel
  call(typeName: string, method: string, ints: number[]): any {
    return Il2Cpp.perform(() => {
      try {
        getAD();
        const cp = findCardPanel();
        if (!cp || cp.isNull()) return { ok: false, err: "no live CardPanel (不在摆牌界面?)" };
        const args = [cp].concat((ints || []).map(boxInt));
        return { ok: true, result: invokeNamed(typeName, method, args) };
      } catch (e) { return { ok: false, err: "" + e }; }
    });
  },
  // call <typeName>.<method>(...ints) WITHOUT CardPanel — for discrete/static actions
  callS(typeName: string, method: string, ints: number[]): any {
    return Il2Cpp.perform(() => {
      try { getAD(); const args = (ints || []).map(boxInt);
        return { ok: true, result: invokeNamed(typeName, method, args) };
      } catch (e) { return { ok: false, err: "" + e }; }
    });
  },
  // reflection: invoke a no-arg method (incl. private) on the live instance of an
  // arbitrary hot-update type (heap-scanned). For private confirms (OnConfirmButtonClick/OnComfirmBtnClick).
  callPrivate(typeName: string, method: string): any {
    return Il2Cpp.perform(() => {
      try {
        getAD();
        let inst: any = null;
        for (const it of Il2Cpp.gc.choose(ITI!)) {
          try { if (raw((it as any).method("get_Type").invoke().method("get_Name").invoke()) === typeName) { inst = it; break; } } catch (_) {}
        }
        if (!inst || inst.isNull()) return { ok: false, err: "no live " + typeName };
        const m = getMethod(typeName, method, 0);
        if (!m) return { ok: false, err: method + " not found on " + typeName };
        INVOKE.invoke(m, inst, Il2Cpp.array(OBJCLS, []));
        return { ok: true, result: "called " + typeName + "." + method };
      } catch (e) { return { ok: false, err: "" + e }; }
    });
  },
  // pick any offered fate/talent on whichever selection panel is live (heap-scan +
  // reflection, avoids generic FindILRSubPanel). TalentSelectionPanel: TalentOnSelect(talent);
  // FateStrategyPanel: set currentSelectedIndex=0 then OnConfirmButtonClick.
  pickAny(): any {
    return Il2Cpp.perform(() => {
      try {
        getAD();
        const scan = (tn: string): any => { for (const it of Il2Cpp.gc.choose(ITI!)) { try { if (raw((it as any).method("get_Type").invoke().method("get_Name").invoke()) === tn) return it; } catch (_) {} } return null; };
        const inv = (it: any, tn: string, m: string, args: any[]): any => { const mm = getMethod(tn, m, args.length); if (!mm) throw new Error(tn+"."+m+" missing"); return INVOKE.invoke(mm, it, Il2Cpp.array(OBJCLS, args)); };
        // talent panel first (breakthrough → TalentSelectionPanel)
        let it = scan("TalentSelectionPanel");
        if (it && !it.isNull()) {
          const tid = parseInt(raw(inv(it, "TalentSelectionPanel", "get_talent", [])), 10);
          inv(it, "TalentSelectionPanel", "TalentOnSelect", [boxInt(tid)]);
          return { ok: true, panel: "TalentSelectionPanel", selected: tid };
        }
        it = scan("FateStrategyPanel");
        if (it && !it.isNull()) {
          inv(it, "FateStrategyPanel", "set_currentSelectedIndex", [boxInt(0)]);
          inv(it, "FateStrategyPanel", "OnConfirmButtonClick", []);
          return { ok: true, panel: "FateStrategyPanel", selected: 0 };
        }
        return { ok: false, err: "no live TalentSelectionPanel / FateStrategyPanel" };
      } catch (e) { return { ok: false, err: "" + e }; }
    });
  },
  // ── proven outbound send (GameClient.SendRoomMessageAsync via ProtobufParser) ──
  // server-authoritative SimpleClientPacts: 突破=type2, 选天衍=type5+param. base64 built in Python.
  sendmsg(typeName: string, base64: string): any {
    return Il2Cpp.perform(() => {
      try {
        getAD();
        // GameClientUtil is HOT-UPDATE → get GameClient via ILRuntime static getter (robust, no heap scan)
        const gm = getMethod("GameClientUtil", "get_client", 0);
        if (!gm) return { ok:false, err:"no GameClientUtil.get_client" };
        const gc:any = INVOKE.invoke(gm, NULL, Il2Cpp.array(OBJCLS, []));
        if (!gc || gc.isNull()) return { ok:false, err:"client null" };
        const pp:any = gc.field("m_RoomParser").value;              // ProtobufParser off the client
        if (!pp || pp.isNull()) return { ok:false, err:"no m_RoomParser" };
        const msg:any = pp.method("DecodeFromBase64",2).invoke(Il2Cpp.string(typeName), Il2Cpp.string(base64));
        if (!msg || msg.isNull()) return { ok:false, err:"decode "+typeName+" failed" };
        gc.method("SendRoomMessageAsync").invoke(msg);
        return { ok:true, sent:typeName, b64:base64 };
      } catch (e) { return { ok:false, err:""+e }; }
    });
  },
  // PROVE native UI output from the bot: game's own HintMessagePanel.Show(string, HintLevel) toast
  toast(msg: string): any {
    return Il2Cpp.perform(() => {
      try {
        const cls = findClassFull("HintMessagePanel", "HintMessagePanel");
        if (!cls) return { ok:false, err:"no HintMessagePanel" };
        cls.method("Show", 2).invoke(Il2Cpp.string(msg), 0);
        return { ok:true, shown:msg };
      } catch (e) { return { ok:false, err:""+e }; }
    });
  },
  // call <typeName>.<method>(string) — for SetDamage/SetRemaining (string args)
  callStr(typeName: string, method: string, str: string): any {
    return Il2Cpp.perform(() => {
      try { getAD();
        const m = getMethod(typeName, method, 1);
        if (!m) return { ok:false, err: typeName+"."+method+" not found" };
        const res = INVOKE.invoke(m, NULL, Il2Cpp.array(OBJCLS, [Il2Cpp.string(str)]));
        return { ok:true, result: raw(res) };
      } catch (e) { return { ok:false, err:""+e }; }
    });
  },
};
console.log("[bot_glue3] ready (rpc: loadBot / ping / call)");
