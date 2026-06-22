import "frida-il2cpp-bridge";

function findClass(name: string): Il2Cpp.Class | null {
  for (const asm of Il2Cpp.domain.assemblies) {
    try { const k = asm.image.class(name); if (k) return k; } catch (_) {}
  }
  return null;
}

function s(x: any): string {
  try { if (x == null) return ""; return x.content != null ? x.content : ("" + x); }
  catch (_) { return ""; }
}

Il2Cpp.perform(() => {
  const pc = findClass("ProtobufParser");
  if (!pc) { console.log("no ProtobufParser"); return; }

  // INBOUND: DecodeFromBase64(string typeName, string base64) → IMessage
  const dec: any = pc.methods.find((m: any) =>
    m.name === "DecodeFromBase64" && m.parameterCount === 2 && !m.virtualAddress.isNull());
  if (dec) {
    const orig = new NativeFunction(dec.virtualAddress, "pointer", ["pointer", "pointer", "pointer", "pointer"]);
    dec.implementation = function (this: any, typeName: any, base64: any) {
      try { send({ dir: "in", t: s(typeName), b: s(base64) }); } catch (_) {}
      return new Il2Cpp.Object(orig(this.handle, typeName.handle, base64.handle, dec.handle) as NativePointer);
    };
    console.log("hooked DecodeFromBase64 (inbound)");
  }

  // OUTBOUND: EncodeToProtobufData(IMessage) → ProtobufData{type, data(base64)}
  const enc: any = pc.method("EncodeToProtobufData");
  if (enc) {
    const orig = new NativeFunction(enc.virtualAddress, "pointer", ["pointer", "pointer", "pointer"]);
    enc.implementation = function (this: any, msg: any) {
      const retPtr = orig(this.handle, msg.handle, enc.handle) as NativePointer;
      try {
        const pd: any = new Il2Cpp.Object(retPtr);     // ProtobufData{ type, data }
        send({ dir: "out", t: s(pd.field("type").value), b: s(pd.field("data").value) });
      } catch (_) {}
      return new Il2Cpp.Object(retPtr);
    };
    console.log("hooked EncodeToProtobufData (outbound)");
  }

  console.log("capture: streaming inbound+outbound {dir, type, base64} to Python");
});
