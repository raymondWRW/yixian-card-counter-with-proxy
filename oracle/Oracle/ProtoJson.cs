// ProtoJson — generic reflection-based round-trip between a game Proto.* message and JSON.
//
// The native engine format IS protobuf (the .bin records deserialize to Proto.RecentBattleInfo via
// wProtobuf). wProtobuf is binary-only, so to make the NATIVE PROTO SHAPE the source of truth for fixtures
// (edited in the web UX, run by the oracle with NO lossy hand-reconstruction), we serialize the proto object
// 1:1 to JSON and back by reflecting over its PUBLIC INSTANCE FIELDS (proto-gen types store data in public
// fields — verified: PlayerData.publicData/privateData are public fields, not auto-props).
//
//   ToNode(protoObj)            -> JsonNode mirroring the proto (field names, nesting, repeated, maps)
//   FromNode(protoType, node)   -> a proto instance rebuilt from that JSON (the inverse)
//
// This replaces the flatten->re-nest round-trip (BuildPlayerDataFromFixture): a native-shaped fixture is just
// FromNode(roundStatType, json) — deserialize, faithful by construction. Round-trip identity is the contract:
// FromNode(t, ToNode(x)) must run identically to x.
using System;
using System.Collections;
using System.Linq;
using System.Reflection;
using System.Text.Json.Nodes;

namespace YiXianOracle;

internal static class ProtoJson
{
    const BindingFlags FIELDS = BindingFlags.Public | BindingFlags.Instance;

    // protobuf-gen internals we must NOT serialize (computed/caches) — they'd break round-trip identity.
    static bool IsInternalField(FieldInfo f) =>
        f.Name.StartsWith("_") || f.Name == "memoizedSize" || f.Name.Contains("k__BackingField");

    static bool IsMessage(Type t) =>
        t.IsClass && t != typeof(string) && !t.IsArray
        && !typeof(IEnumerable).IsAssignableFrom(t) && t.Name != "ByteString";

    // ── proto -> JSON ─────────────────────────────────────────────────────────────────────────────────
    internal static JsonNode? ToNode(object? o)
    {
        if (o == null) return null;
        var t = o.GetType();
        switch (o)
        {
            case string s: return JsonValue.Create(s);
            case bool b: return JsonValue.Create(b);
            case float f: return JsonValue.Create(f);
            case double d: return JsonValue.Create(d);
            case byte[] bytes: return JsonValue.Create(Convert.ToBase64String(bytes));
        }
        if (t.IsEnum) return JsonValue.Create(Convert.ToInt64(o));
        if (t.IsPrimitive) return JsonValue.Create(Convert.ToInt64(o));          // int/long/uint/ulong/short/byte
        if (t.Name == "ByteString")                                              // wProtobuf ByteString
        {
            var arr = t.GetMethod("ToByteArray")?.Invoke(o, null) as byte[] ?? Array.Empty<byte>();
            return JsonValue.Create(Convert.ToBase64String(arr));
        }
        if (o is IDictionary dict)
        {
            var obj = new JsonObject();
            foreach (DictionaryEntry kv in dict) obj[Convert.ToString(KeyToScalar(kv.Key))!] = ToNode(kv.Value);
            return obj;
        }
        if (o is IEnumerable en)
        {
            var arr = new JsonArray();
            foreach (var item in en) arr.Add(ToNode(item));
            return arr;
        }
        // proto message: mirror its public instance fields
        var msg = new JsonObject();
        foreach (var f in t.GetFields(FIELDS).Where(f => !IsInternalField(f)))
            msg[f.Name] = ToNode(f.GetValue(o));
        return msg;
    }

    static object KeyToScalar(object k) => k.GetType().IsEnum ? Convert.ToInt64(k) : k;

    // ── JSON -> proto ─────────────────────────────────────────────────────────────────────────────────
    internal static object? FromNode(Type t, JsonNode? n)
    {
        if (n == null) return t.IsValueType ? Activator.CreateInstance(t) : null;
        if (t == typeof(string)) return n.GetValue<string>();
        if (t == typeof(bool)) return n.GetValue<bool>();
        if (t == typeof(float)) return (float)n.GetValue<double>();
        if (t == typeof(double)) return n.GetValue<double>();
        if (t == typeof(byte[])) return Convert.FromBase64String(n.GetValue<string>());
        if (t.IsEnum) return Enum.ToObject(t, n.GetValue<long>());
        if (t.IsPrimitive) return Convert.ChangeType(n.GetValue<long>(), t);
        if (t.Name == "ByteString")
            return Activator.CreateInstance(t, Convert.FromBase64String(n.GetValue<string>()));
        if (typeof(IDictionary).IsAssignableFrom(t))
        {
            var dict = (IDictionary)Activator.CreateInstance(t)!;
            var args = t.GetGenericArguments(); var kt = args[0]; var vt = args[1];
            foreach (var kv in (JsonObject)n)
            {
                object key = kt.IsEnum ? Enum.ToObject(kt, long.Parse(kv.Key))
                    : Convert.ChangeType(kv.Key, Nullable.GetUnderlyingType(kt) ?? kt);
                dict[key] = FromNode(vt, kv.Value);
            }
            return dict;
        }
        if (typeof(IList).IsAssignableFrom(t) && t.IsGenericType)
        {
            var list = (IList)Activator.CreateInstance(t)!;
            var et = t.GetGenericArguments()[0];
            foreach (var item in (JsonArray)n) list.Add(FromNode(et, item));
            return list;
        }
        // proto message: build instance, set each public field present in the JSON
        var obj = Activator.CreateInstance(t)!;
        var jo = (JsonObject)n;
        foreach (var f in t.GetFields(FIELDS).Where(f => !IsInternalField(f)))
            if (jo.TryGetPropertyValue(f.Name, out var fn) && fn != null)
            {
                var val = FromNode(f.FieldType, fn);
                if (val != null) f.SetValue(obj, val);
            }
        return obj;
    }
}
