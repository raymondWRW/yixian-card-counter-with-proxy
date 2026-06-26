// DarkSun.Utility facade
using System;
using System.Collections.Generic;
using UnityEngine;

namespace DarkSun
{
    public class Singleton<T> where T : class, new() { private static T _i; public static T Instance { get { if (_i == null) _i = new T(); return _i; } } }
    public class MonoSingleton<T> : MonoBehaviour where T : MonoBehaviour { public static T Instance => null; }
    public static class Log { public static void Info(string m) { } public static void Info(string t, string m) { } public static void Warning(string m) { } public static void Warning(string t, string m) { } public static void Error(string m) { } public static void Error(string t, string m) { } }
}

namespace DarkSun.Utility
{
    public class Timer { public float Duration { get; set; } public float Elapsed { get; set; } public bool IsRunning { get; set; } public void Start() { } public void Stop() { } public void Reset() { } public void Update(float dt) { } }
    public class ObjectPool<T> where T : class, new() { public T Get() => new T(); public void Release(T o) { } }
    public static class ListExtensions { public static void Shuffle<T>(this IList<T> l) { } public static T RandomItem<T>(this IList<T> l) => l.Count > 0 ? l[0] : default; }
    // StringExtensions moved to global namespace below
    public static class EventManager { public static void Register(string e, Action c) { } public static void Register<T>(string e, Action<T> c) { } public static void Unregister(string e, Action c) { } public static void Unregister<T>(string e, Action<T> c) { } public static void Trigger(string e) { } public static void Trigger<T>(string e, T a) { } }
    public static class ConfigManager { public static string GetString(string k, string d = "") => d; public static int GetInt(string k, int d = 0) => d; public static float GetFloat(string k, float d = 0) => d; public static bool GetBool(string k, bool d = false) => d; }
    public class ResourceManager { public static T Load<T>(string p) where T : UnityEngine.Object => null; public static void LoadAsync<T>(string p, Action<T> c) where T : UnityEngine.Object { } }
    public static class Localization { public static string Get(string k) => k; public static string Get(string k, params object[] a) => string.Format(k, a); public static SystemLanguage CurrentLanguage { get; set; } }

}

// Types referenced from game DLL without namespace qualifiers (in global namespace of DarkSun.Utility)
public class ILRFancyDataBase { }

// Game settings (global namespace). Combat reads InternalSettingsManager.settings.language to pick
// localized card text — purely cosmetic. Headless we keep defaults.
public enum LanguageType { English, ChineseSimplified, ChineseTraditional, Japanese, Korean }
public class InternalSettings { public LanguageType language; public float bgmVolume = 1f; public float sfxVolume = 1f; public bool muteWhenInBackground; }
public static class InternalSettingsManager
{
    public static InternalSettings settings { get; } = new InternalSettings();
    public static UnityEngine.Events.UnityEvent onLanguageChanged { get; } = new UnityEngine.Events.UnityEvent();
    public static void ChangeLanguage(LanguageType t) { settings.language = t; }
}
public class Response { public int code; public string msg; }
public static class StringExtensions
{
    public static string Translate(this string key, object a1 = null, object a2 = null) => key;
    public static string Translate(this string key, params object[] args) => key;
    public static bool IsNullOrEmpty(this string s) => string.IsNullOrEmpty(s);
}
public static class TransformExtensions
{
    public static void Reset(UnityEngine.Transform t) { }
}
public static class DisposableExtensions
{
    public static T AddTo<T>(T d, UnityEngine.Component c) => d;
}
public static class EffectFactory
{
    // Absorb (return non-null dummy so chained calls don't crash) + record the FX for the renderer.
    public static UnityEngine.Transform Spawn(string name, UnityEngine.Vector3 pos, float dur = -1f)
        { UnityEngine.RenderSink.Emit("Fx", name, pos); return UnityEngine.RenderSink.Dummy; }
    public static UnityEngine.Transform Spawn(string name, UnityEngine.Vector3 pos, UnityEngine.Quaternion? rot = null, float dur = -1f)
        { UnityEngine.RenderSink.Emit("Fx", name, pos); return UnityEngine.RenderSink.Dummy; }
    public static UnityEngine.Transform Spawn(string name, UnityEngine.Transform parent, float dur = -1f)
        { UnityEngine.RenderSink.Emit("Fx", name); return UnityEngine.RenderSink.Dummy; }
    public static void DespawnTrailingParticles(UnityEngine.Transform t) { }
    public static void Despawn(UnityEngine.Transform t) { }
}
public static class AssetNameUtil
{
    public static string GetDefeatEffectPrefabPath(int effectId, int level) => "";
}
public static class CommonUtils
{
    public static System.IDisposable DelaySecondDoAction(float seconds, System.Action action, bool ignoreTimeScale = false) => null;
    public static System.IDisposable DelayFrameDoAction(int frames, System.Action action, bool ignoreTimeScale = false) => null;
}
public class PrefabPool<T> where T : UnityEngine.Component
{
    private static T _stub;
    public T Spawn(UnityEngine.Transform parent = null)
    {
        if (_stub == null)
        {
            try { _stub = System.Activator.CreateInstance<T>(); }
            catch { return null; }
        }
        return _stub;
    }
    public void Despawn(T obj) { }
    public void DespawnAll() { }
    public void Clear() { }
}

// UI extension stubs
public static class UIExtensions
{
    public static void SetParent(this UnityEngine.RectTransform rt, UnityEngine.RectTransform parent, bool worldPositionStays = true) { }
    public static void FillParent(this UnityEngine.RectTransform rt) { }
}

// I2 Localization stubs (referenced via DarkSun.Utility)
namespace I2.Loc
{
    public static class LocalizationManager
    {
        public static string CurrentLanguage { get; set; } = "en";
        public static string GetTranslation(string term) => term;
        public static string GetTranslation(string term, bool fixForRTL = true, int maxLineLengthForRTL = 0, bool ignoreRTLnumbers = true, bool applyParameters = false, UnityEngine.GameObject localParametersRoot = null, string overrideLanguage = null) => term;
        public static bool TryGetTranslation(string term, out string translation) { translation = term; return true; }
    }
}

// ILR (IL Runtime) hot update framework types
public class ILRComponentBridge : UnityEngine.MonoBehaviour
{
    public static readonly System.Collections.Generic.Dictionary<System.Type, object> _ilrCache = new();
    public T GetILRObject<T>() where T : class
    {
        var type = typeof(T);
        if (_ilrCache.TryGetValue(type, out var cached)) return cached as T;
        T obj = null;
        try { obj = System.Activator.CreateInstance(type) as T; } catch { }
        if (obj == null)
        {
            // MonoBehaviour subclasses can't use new() — create raw object via reflection
            try
            {
                var ctor = type.GetConstructor(
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic,
                    null, System.Type.EmptyTypes, null);
                if (ctor != null) obj = ctor.Invoke(null) as T;
            }
            catch { }
        }
        // Initialize m_Transform on ILRComponentBase subclasses so UI code doesn't crash
        if (obj != null)
        {
            var mTransformField = type.GetField("m_Transform",
                System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
            if (mTransformField == null)
            {
                // Walk up base types to find it
                var baseType = type.BaseType;
                while (baseType != null && mTransformField == null)
                {
                    mTransformField = baseType.GetField("m_Transform",
                        System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                    baseType = baseType.BaseType;
                }
            }
            if (mTransformField != null && mTransformField.GetValue(obj) == null)
            {
                mTransformField.SetValue(obj, new UnityEngine.RectTransform());
            }
        }
        _ilrCache[type] = obj;
        return obj;
    }
}
public struct ILRVariable
{
    public string name;
    public UnityEngine.Object value;
}

// Additional DarkSun.Utility types used by battle code
public static class CharacterBattleAnimatorPool
{
    public static object Spawn(UnityEngine.Transform parent, object data) => null;
}
public static class BattleSceneManager
{
    public static object currentSceneParams => null;
}
public class BattleSceneParams : UnityEngine.MonoBehaviour
{
    public UnityEngine.Color shadowColor;
    public float shadowRotation;
    public float shadowScale;
}

// ProtobufParser — global-namespace proto serializer in the DarkSun.Utility assembly. Combat only hits
// EncodeToBase64 (a "battle result mismatch" log path during replay). Stub the called surface so CoreCLR
// can load the type natively (native binds strictly by signature; ILRuntime resolved it lazily).
public class ProtobufParser
{
    private static ProtobufParser _main = new ProtobufParser();
    public static ProtobufParser main => _main;
    public string protoNamespace { get; set; }
    public ProtobufParser(int bufferCapacity = 4096) { }
    public byte[] Encode(wProtobuf.IMessage message) => System.Array.Empty<byte>();
    public string EncodeToBase64(wProtobuf.IMessage message) => "";
    public T Decode<T>(byte[] bytes) => default;
    public T DecodeFromBase64<T>(string base64) => default;
}
