// trace_out.ts — log every OUTBOUND request (the game's own EncodeToProtobufData),
// so when the user clicks the real 突破 button we see exactly what message it sends.
// Reuses the proven hook from autoplay/inject/capture.ts (outbound only, less noise).
import "frida-il2cpp-bridge";

function findClass(name: string): Il2Cpp.Class | null {
  for (const asm of Il2Cpp.domain.assemblies) { try { const k = asm.image.class(name); if (k) return k; } catch (_) {} }
  return null;
}
function s(x: any): string { try { if (x == null) return ""; return x.content != null ? x.content : ("" + x); } catch (_) { return ""; } }

Il2Cpp.perform(() => {
  const pc = findClass("ProtobufParser");
  if (!pc) { console.log("no ProtobufParser"); return; }
  const enc: any = pc.method("EncodeToProtobufData");
  if (!enc) { console.log("no EncodeToProtobufData"); return; }
  const orig = new NativeFunction(enc.virtualAddress, "pointer", ["pointer", "pointer", "pointer"]);
  enc.implementation = function (this: any, msg: any) {
    const retPtr = orig(this.handle, msg.handle, enc.handle) as NativePointer;
    try { const pd: any = new Il2Cpp.Object(retPtr); send({ dir: "out", t: s(pd.field("type").value), b: s(pd.field("data").value) }); } catch (_) {}
    return new Il2Cpp.Object(retPtr);
  };
  console.log("[trace_out] hooked EncodeToProtobufData — streaming OUTBOUND {type, base64}");
});
