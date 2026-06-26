// UnityEngine.CoreModule facade — core value types, Object hierarchy, MonoBehaviour, etc.
// This is the foundation assembly that most other Unity assemblies reference.
using System;
using System.Collections;
using System.Collections.Generic;

namespace UnityEngine
{
    // ─── Value types ─────────────────────────────────────────
    public struct Vector2
    {
        public float x, y;
        public Vector2(float x, float y) { this.x = x; this.y = y; }
        public static Vector2 zero => new Vector2(0, 0);
        public static Vector2 one => new Vector2(1, 1);
        public static Vector2 up => new Vector2(0, 1);
        public static Vector2 down => new Vector2(0, -1);
        public static Vector2 left => new Vector2(-1, 0);
        public static Vector2 right => new Vector2(1, 0);
        public float magnitude => (float)Math.Sqrt(x * x + y * y);
        public static Vector2 operator +(Vector2 a, Vector2 b) => new Vector2(a.x + b.x, a.y + b.y);
        public static Vector2 operator -(Vector2 a, Vector2 b) => new Vector2(a.x - b.x, a.y - b.y);
        public static Vector2 operator *(Vector2 a, float d) => new Vector2(a.x * d, a.y * d);
        public static Vector2 operator *(float d, Vector2 a) => new Vector2(a.x * d, a.y * d);
        public static float Distance(Vector2 a, Vector2 b) => (a - b).magnitude;
        public static implicit operator Vector3(Vector2 v) => new Vector3(v.x, v.y, 0);
        public static implicit operator Vector2(Vector3 v) => new Vector2(v.x, v.y);
    }

    public struct Vector2Int
    {
        public int x, y;
        public Vector2Int(int x, int y) { this.x = x; this.y = y; }
    }

    public struct Vector3
    {
        public float x, y, z;
        public Vector3(float x, float y, float z) { this.x = x; this.y = y; this.z = z; }
        public Vector3(float x, float y) { this.x = x; this.y = y; this.z = 0; }
        public static Vector3 zero => new Vector3(0, 0, 0);
        public static Vector3 one => new Vector3(1, 1, 1);
        public static Vector3 up => new Vector3(0, 1, 0);
        public static Vector3 down => new Vector3(0, -1, 0);
        public static Vector3 left => new Vector3(-1, 0, 0);
        public static Vector3 right => new Vector3(1, 0, 0);
        public static Vector3 forward => new Vector3(0, 0, 1);
        public static Vector3 back => new Vector3(0, 0, -1);
        public float magnitude => (float)Math.Sqrt(x * x + y * y + z * z);
        public float sqrMagnitude => x * x + y * y + z * z;
        public static bool operator ==(Vector3 a, Vector3 b) => (a - b).sqrMagnitude < 9.99999944E-11f;
        public static bool operator !=(Vector3 a, Vector3 b) => !(a == b);
        public override bool Equals(object o) => o is Vector3 v && x == v.x && y == v.y && z == v.z;
        public override int GetHashCode() => x.GetHashCode() ^ (y.GetHashCode() << 2) ^ (z.GetHashCode() >> 2);
        public static Vector3 operator +(Vector3 a, Vector3 b) => new Vector3(a.x + b.x, a.y + b.y, a.z + b.z);
        public static Vector3 operator -(Vector3 a, Vector3 b) => new Vector3(a.x - b.x, a.y - b.y, a.z - b.z);
        public static Vector3 operator *(Vector3 a, float d) => new Vector3(a.x * d, a.y * d, a.z * d);
        public static Vector3 operator *(float d, Vector3 a) => new Vector3(a.x * d, a.y * d, a.z * d);
        public static Vector3 Lerp(Vector3 a, Vector3 b, float t) => a + (b - a) * t;
        public static float Distance(Vector3 a, Vector3 b) => (a - b).magnitude;
    }

    public struct Vector3Int
    {
        public int x, y, z;
        public Vector3Int(int x, int y, int z) { this.x = x; this.y = y; this.z = z; }
    }

    public struct Vector4
    {
        public float x, y, z, w;
        public Vector4(float x, float y, float z, float w) { this.x = x; this.y = y; this.z = z; this.w = w; }
    }

    // Was missing from this facade -> CardItem visual methods (ResetDescription, SetKeywordGray,
    // RefreshAttatchKeyWordCardDesc, ...) TypeLoad-faulted, aborting card plays (e.g. Li Man's stance
    // never toggled). Minimal stub: the game only calls MultiplyPoint3x4.
    public struct Matrix4x4
    {
        public float m00, m10, m20, m30, m01, m11, m21, m31, m02, m12, m22, m32, m03, m13, m23, m33;
        public static Matrix4x4 identity => default;
        public Vector3 MultiplyPoint3x4(Vector3 point) => default;
        public Vector3 MultiplyPoint(Vector3 point) => default;
        public Vector3 MultiplyVector(Vector3 vector) => default;
    }

    public struct Color
    {
        public float r, g, b, a;
        public Color(float r, float g, float b, float a) { this.r = r; this.g = g; this.b = b; this.a = a; }
        public Color(float r, float g, float b) { this.r = r; this.g = g; this.b = b; this.a = 1f; }
        public static Color red => new Color(1, 0, 0, 1);
        public static Color green => new Color(0, 1, 0, 1);
        public static Color blue => new Color(0, 0, 1, 1);
        public static Color white => new Color(1, 1, 1, 1);
        public static Color black => new Color(0, 0, 0, 1);
        public static Color yellow => new Color(1, 0.92f, 0.016f, 1);
        public static Color cyan => new Color(0, 1, 1, 1);
        public static Color magenta => new Color(1, 0, 1, 1);
        public static Color gray => new Color(0.5f, 0.5f, 0.5f, 1);
        public static Color grey => gray;
        public static Color clear => new Color(0, 0, 0, 0);
        public static Color Lerp(Color a, Color b, float t) => new Color(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, a.a + (b.a - a.a) * t);
    }

    public struct Color32
    {
        public byte r, g, b, a;
        public Color32(byte r, byte g, byte b, byte a) { this.r = r; this.g = g; this.b = b; this.a = a; }
        public static implicit operator Color(Color32 c) => new Color(c.r / 255f, c.g / 255f, c.b / 255f, c.a / 255f);
        public static implicit operator Color32(Color c) => new Color32((byte)(c.r * 255), (byte)(c.g * 255), (byte)(c.b * 255), (byte)(c.a * 255));
    }

    public struct Quaternion
    {
        public float x, y, z, w;
        public Quaternion(float x, float y, float z, float w) { this.x = x; this.y = y; this.z = z; this.w = w; }
        public static Quaternion identity => new Quaternion(0, 0, 0, 1);
        public static Quaternion Euler(float x, float y, float z) => identity;
        public static Quaternion Euler(Vector3 euler) => identity;
        public Vector3 eulerAngles { get { return Vector3.zero; } set { } }
    }

    public struct Rect
    {
        public float x, y, width, height;
        public Rect(float x, float y, float w, float h) { this.x = x; this.y = y; width = w; height = h; }
    }

    public struct Bounds
    {
        public Vector3 center, size;
        public Bounds(Vector3 c, Vector3 s) { center = c; size = s; }
    }

    public struct LayerMask
    {
        public int value;
        public static implicit operator int(LayerMask m) => m.value;
        public static implicit operator LayerMask(int v) { var m = new LayerMask(); m.value = v; return m; }
    }

    public struct Resolution { public int width, height, refreshRate; }
    public struct RaycastHit { public Vector3 point, normal; public float distance; }
    public struct Ray { public Vector3 origin, direction; public Ray(Vector3 o, Vector3 d) { origin = o; direction = d; } }

    // ─── Mathf ───────────────────────────────────────────────
    public static class Mathf
    {
        public const float PI = 3.14159274f;
        public const float Infinity = float.PositiveInfinity;
        public const float NegativeInfinity = float.NegativeInfinity;
        public const float Deg2Rad = PI / 180f;
        public const float Rad2Deg = 180f / PI;
        public const float Epsilon = 1.401298E-45f;
        public static float Abs(float f) => Math.Abs(f);
        public static int Abs(int v) => Math.Abs(v);
        public static int CeilToInt(float f) => (int)Math.Ceiling(f);
        public static int FloorToInt(float f) => (int)Math.Floor(f);
        public static int RoundToInt(float f) => (int)Math.Round(f);
        public static float Ceil(float f) => (float)Math.Ceiling(f);
        public static float Floor(float f) => (float)Math.Floor(f);
        public static float Round(float f) => (float)Math.Round(f);
        public static float Clamp(float v, float min, float max) => v < min ? min : v > max ? max : v;
        public static int Clamp(int v, int min, int max) => v < min ? min : v > max ? max : v;
        public static float Clamp01(float v) => Clamp(v, 0f, 1f);
        public static float Lerp(float a, float b, float t) => a + (b - a) * Clamp01(t);
        public static float LerpUnclamped(float a, float b, float t) => a + (b - a) * t;
        public static float Max(float a, float b) => a > b ? a : b;
        public static int Max(int a, int b) => a > b ? a : b;
        public static float Max(params float[] v) { float m = float.NegativeInfinity; for (int i = 0; i < v.Length; i++) if (v[i] > m) m = v[i]; return m; }
        public static int Max(params int[] v) { int m = int.MinValue; for (int i = 0; i < v.Length; i++) if (v[i] > m) m = v[i]; return m; }
        public static float Min(float a, float b) => a < b ? a : b;
        public static int Min(int a, int b) => a < b ? a : b;
        public static float Min(params float[] v) { float m = float.PositiveInfinity; for (int i = 0; i < v.Length; i++) if (v[i] < m) m = v[i]; return m; }
        public static int Min(params int[] v) { int m = int.MaxValue; for (int i = 0; i < v.Length; i++) if (v[i] < m) m = v[i]; return m; }
        public static float Pow(float f, float p) => (float)Math.Pow(f, p);
        public static float Sqrt(float f) => (float)Math.Sqrt(f);
        public static float Sin(float f) => (float)Math.Sin(f);
        public static float Cos(float f) => (float)Math.Cos(f);
        public static float Tan(float f) => (float)Math.Tan(f);
        public static float Atan2(float y, float x) => (float)Math.Atan2(y, x);
        public static float Log(float f) => (float)Math.Log(f);
        public static float Log10(float f) => (float)Math.Log10(f);
        public static float Sign(float f) => f >= 0 ? 1f : -1f;
        public static bool Approximately(float a, float b) => Abs(b - a) < Max(1E-06f * Max(Abs(a), Abs(b)), Epsilon * 8f);
        public static float Repeat(float t, float length) => Clamp(t - Floor(t / length) * length, 0, length);
        public static float MoveTowards(float c, float t, float d) { if (Abs(t - c) <= d) return t; return c + Sign(t - c) * d; }
        public static float SmoothStep(float from, float to, float t) { t = Clamp01(t); t = -2f * t * t * t + 3f * t * t; return to * t + from * (1f - t); }
        public static float InverseLerp(float a, float b, float v) { if (a != b) return Clamp01((v - a) / (b - a)); return 0f; }
    }

    // ─── Object hierarchy ────────────────────────────────────
    public class Object
    {
        public string name { get; set; }
        public int GetInstanceID() => GetHashCode();
        public static void Destroy(Object obj) { }
        public static void Destroy(Object obj, float t) { }
        public static void DestroyImmediate(Object obj) { }
        public static void DontDestroyOnLoad(Object target) { }
        public static T FindObjectOfType<T>() where T : Object => null;
        public static T[] FindObjectsOfType<T>() where T : Object => new T[0];
        public static T Instantiate<T>(T original) where T : Object => original;
        public static T Instantiate<T>(T original, Transform parent) where T : Object => original;
        public static T Instantiate<T>(T original, Vector3 position, Quaternion rotation) where T : Object => original;
        public static Object Instantiate(Object original) => original;
        public static Object Instantiate(Object original, Transform parent) => original;
        public static implicit operator bool(Object obj) => obj != null;
        public static bool operator ==(Object a, Object b) => ReferenceEquals(a, b);
        public static bool operator !=(Object a, Object b) => !ReferenceEquals(a, b);
        public override bool Equals(object other) => ReferenceEquals(this, other);
        public override int GetHashCode() => base.GetHashCode();
        public override string ToString() => name ?? base.ToString();
    }

    public class Component : Object
    {
        // Lazily non-null (like transform): combat/visual code does `this.someVMField.gameObject
        // .SetActive(...)` on scene-injected components; headless those gameObjects are unset, and a
        // null deref there NREs natively (no AbsorbVisualNulls). A lazy non-null keeps the graph safe.
        private GameObject _gameObject;
        public GameObject gameObject { get => _gameObject ??= new GameObject(); set => _gameObject = value; }
        private Transform _transform;
        public Transform transform { get => _transform ?? (_transform = new Transform()); set => _transform = value; }
        public string tag { get; set; }
        public T GetComponent<T>()
        {
            // Return a stub instance for common component types to prevent NullRef in UI code
            try { return System.Activator.CreateInstance<T>(); }
            catch { return default; }
        }
        public T GetComponentInChildren<T>()
        {
            try { return System.Activator.CreateInstance<T>(); }
            catch { return default; }
        }
        public T GetComponentInChildren<T>(bool includeInactive)
        {
            try { return System.Activator.CreateInstance<T>(); }
            catch { return default; }
        }
        public T GetComponentInParent<T>()
        {
            try { return System.Activator.CreateInstance<T>(); }
            catch { return default; }
        }
        public T[] GetComponents<T>() => new T[0];
        public T[] GetComponentsInChildren<T>() => new T[0];
        public T[] GetComponentsInChildren<T>(bool includeInactive) => new T[0];
        public Component GetComponent(Type type) => null;
        public Component GetComponent(string type) => null;
        public bool CompareTag(string tag) => false;
        public void SendMessage(string methodName) { }
        public void SendMessage(string methodName, object value) { }
        public void BroadcastMessage(string methodName) { }
    }

    public class Behaviour : Component
    {
        public bool enabled { get; set; }
        public bool isActiveAndEnabled => enabled;
    }

    public class MonoBehaviour : Behaviour
    {
        public Coroutine StartCoroutine(IEnumerator routine) => null;
        public Coroutine StartCoroutine(string methodName) => null;
        public Coroutine StartCoroutine(string methodName, object value) => null;
        public void StopCoroutine(Coroutine routine) { }
        public void StopCoroutine(string methodName) { }
        public void StopCoroutine(IEnumerator routine) { }
        public void StopAllCoroutines() { }
        public void Invoke(string methodName, float time) { }
        public void InvokeRepeating(string methodName, float time, float repeatRate) { }
        public void CancelInvoke() { }
        public void CancelInvoke(string methodName) { }
        public bool IsInvoking() => false;
        public bool IsInvoking(string methodName) => false;
        public static void print(object message) { }
    }

    public class Coroutine : YieldInstruction { }
    public class YieldInstruction { }
    public class WaitForSeconds : YieldInstruction { public WaitForSeconds(float s) { } }
    public class WaitForEndOfFrame : YieldInstruction { }
    public class WaitForFixedUpdate : YieldInstruction { }
    public class WaitUntil : CustomYieldInstruction { public WaitUntil(Func<bool> p) { } public override bool keepWaiting => false; }
    public class WaitWhile : CustomYieldInstruction { public WaitWhile(Func<bool> p) { } public override bool keepWaiting => false; }
    public abstract class CustomYieldInstruction : IEnumerator
    {
        public abstract bool keepWaiting { get; }
        public object Current => null;
        public bool MoveNext() => keepWaiting;
        public void Reset() { }
    }

    // ─── GameObject & Transform ──────────────────────────────
    public class GameObject : Object
    {
        public Transform transform { get; set; }
        public bool activeSelf { get; set; }
        public bool activeInHierarchy => activeSelf;
        public int layer { get; set; }
        public string tag { get; set; }
        public GameObject() { transform = new Transform(); }
        public GameObject(string name) { this.name = name; transform = new Transform(); }
        public GameObject(string name, params Type[] components) { this.name = name; transform = new Transform(); }
        public void SetActive(bool value) { activeSelf = value; }
        public T GetComponent<T>()
        {
            // Return type-specific stubs: Transform → our transform, otherwise try create
            if (typeof(T) == typeof(Transform) || typeof(T) == typeof(RectTransform))
                return (T)(object)(transform ?? new Transform());
            try { return System.Activator.CreateInstance<T>(); }
            catch { return default; }
        }
        public T GetComponentInChildren<T>()
        {
            try { return System.Activator.CreateInstance<T>(); }
            catch { return default; }
        }
        public T GetComponentInParent<T>()
        {
            try { return System.Activator.CreateInstance<T>(); }
            catch { return default; }
        }
        public T[] GetComponents<T>() => new T[0];
        public T[] GetComponentsInChildren<T>() => new T[0];
        public T[] GetComponentsInChildren<T>(bool includeInactive) => new T[0];
        public Component GetComponent(Type type) => null;
        public Component GetComponent(string type) => null;
        public T AddComponent<T>() where T : Component, new() => new T();
        public Component AddComponent(Type componentType) => null;
        public static GameObject Find(string name) => null;
        public static GameObject[] FindGameObjectsWithTag(string tag) => new GameObject[0];
    }

    public class Transform : Component, IEnumerable
    {
        public Vector3 position { get; set; }
        public Vector3 localPosition { get; set; }
        public Quaternion rotation { get; set; }
        public Quaternion localRotation { get; set; }
        public Vector3 localScale { get; set; }
        public Vector3 eulerAngles { get; set; }
        public Vector3 localEulerAngles { get; set; }
        public Vector3 lossyScale => localScale;
        public Transform parent { get; set; }
        public Transform() { transform = this; parent = this; localScale = Vector3.one; }
        public int childCount => 0;
        public Vector3 forward { get { return Vector3.forward; } set { } }
        public Vector3 right { get { return Vector3.right; } set { } }
        public Vector3 up { get { return Vector3.up; } set { } }
        public Transform GetChild(int index) => new Transform();
        public Transform Find(string n) => new Transform();
        public void SetParent(Transform p) { parent = p; }
        public void SetParent(Transform p, bool worldPositionStays) { parent = p; }
        public void SetAsFirstSibling() { }
        public void SetAsLastSibling() { }
        public void SetSiblingIndex(int index) { }
        public int GetSiblingIndex() => 0;
        public void LookAt(Transform target) { }
        public void LookAt(Vector3 worldPosition) { }
        public void Rotate(Vector3 eulers) { }
        public void Rotate(Vector3 axis, float angle) { }
        public void Translate(Vector3 translation) { }
        public IEnumerator GetEnumerator() => new List<Transform>().GetEnumerator();
    }

    public class RectTransform : Transform
    {
        public Vector2 anchoredPosition { get; set; }
        public Vector2 sizeDelta { get; set; }
        public Vector2 anchorMin { get; set; }
        public Vector2 anchorMax { get; set; }
        public Vector2 pivot { get; set; }
        public Vector2 offsetMin { get; set; }
        public Vector2 offsetMax { get; set; }
        public Rect rect => new Rect();
    }

    // ─── Renderers ───────────────────────────────────────────
    public class Renderer : Component
    {
        public Material material { get; set; }
        public Material sharedMaterial { get; set; }
        public Material[] materials { get; set; }
        public bool enabled { get; set; }
        public Bounds bounds => new Bounds();
        public int sortingOrder { get; set; }
        public string sortingLayerName { get; set; }
    }

    public class SpriteRenderer : Renderer
    {
        public Sprite sprite { get; set; }
        public Color color { get; set; }
        public bool flipX { get; set; }
        public bool flipY { get; set; }
    }

    public class MeshRenderer : Renderer { }

    // ─── Assets ──────────────────────────────────────────────
    public class Sprite : Object { public Rect rect => new Rect(); public Texture2D texture => null; public Vector2 pivot => Vector2.zero; }
    public class Texture : Object { public int width => 0; public int height => 0; }
    public class Texture2D : Texture
    {
        public Texture2D(int w, int h) { }
        public Color GetPixel(int x, int y) => Color.black;
        public void SetPixel(int x, int y, Color c) { }
        public void Apply() { }
        public byte[] EncodeToPNG() => new byte[0];
    }
    public class RenderTexture : Texture { public RenderTexture(int w, int h, int d) { } }
    public class Material : Object
    {
        public Material(Shader s) { }
        public Material(Material m) { }
        public Color color { get; set; }
        public Shader shader { get; set; }
        public float GetFloat(string n) => 0; public void SetFloat(string n, float v) { }
        public Color GetColor(string n) => Color.white; public void SetColor(string n, Color v) { }
        public void SetTexture(string n, Texture v) { }
        public void SetInt(string n, int v) { }
        public bool HasProperty(string n) => false;
    }
    public class Shader : Object { public static Shader Find(string n) => null; }
    public class ScriptableObject : Object { public static T CreateInstance<T>() where T : ScriptableObject, new() => new T(); }
    public class TextAsset : Object
    {
        private byte[] _bytes;
        public TextAsset() { _bytes = new byte[0]; }
        public TextAsset(byte[] data) { _bytes = data ?? new byte[0]; }
        public string text => System.Text.Encoding.UTF8.GetString(_bytes);
        public byte[] bytes => _bytes;
    }
    public class Font : Object { }

    // ─── Camera ──────────────────────────────────────────────
    public class Camera : Behaviour
    {
        public static Camera main => null;
        public float orthographicSize { get; set; }
        public bool orthographic { get; set; }
        public float fieldOfView { get; set; }
        public float nearClipPlane { get; set; }
        public float farClipPlane { get; set; }
        public Rect rect { get; set; }
        public Color backgroundColor { get; set; }
        public int depth { get; set; }
        public Vector3 ScreenToWorldPoint(Vector3 p) => p;
        public Vector3 WorldToScreenPoint(Vector3 p) => p;
        public Ray ScreenPointToRay(Vector3 p) => new Ray();
    }

    // ─── CanvasGroup ─────────────────────────────────────────
    public class CanvasGroup : Behaviour
    {
        public float alpha { get; set; }
        public bool interactable { get; set; }
        public bool blocksRaycasts { get; set; }
    }
    public class Canvas : Behaviour
    {
        public int sortingOrder { get; set; }
        public RenderMode renderMode { get; set; }
        public Camera worldCamera { get; set; }
    }
    public enum RenderMode { ScreenSpaceOverlay, ScreenSpaceCamera, WorldSpace }

    // ─── Static utilities ────────────────────────────────────
    // Absorb-and-record sink: visual facade calls emit a render event here (wired from the Oracle),
    // then return a non-null dummy. One hook = both "absorb the visual call" and "capture it for the renderer".
    public static class RenderSink
    {
        public static Action<string, object[]> OnEvent;
        public static void Emit(string kind, params object[] args) => OnEvent?.Invoke(kind, args);
        // Shared dummy transform so chained visual calls (.position, DOMoveX, etc.) never null-crash.
        public static readonly Transform Dummy = new Transform();
    }

    public static class Debug
    {
        public static Action<string> OnLog;
        public static void Log(object m) => OnLog?.Invoke(m?.ToString());
        public static void Log(object m, Object c) => OnLog?.Invoke(m?.ToString());
        public static void LogWarning(object m) => OnLog?.Invoke($"[WARN] {m}");
        public static void LogWarning(object m, Object c) => OnLog?.Invoke($"[WARN] {m}");
        public static void LogError(object m) => OnLog?.Invoke($"[ERR] {m}");
        public static void LogError(object m, Object c) => OnLog?.Invoke($"[ERR] {m}");
        public static Action<Exception> OnException;
        public static void LogException(Exception e) { OnException?.Invoke(e); OnLog?.Invoke($"[EXC] {e.Message}"); }
    }

    public static class Application
    {
        public static string dataPath => "";
        public static string persistentDataPath => "";
        public static string streamingAssetsPath => "";
        public static string temporaryCachePath => "";
        public static RuntimePlatform platform => RuntimePlatform.WindowsPlayer;
        public static string version => "0.0.0";
        public static string productName => "";
        public static string companyName => "";
        public static string identifier => "";
        public static SystemLanguage systemLanguage => SystemLanguage.English;
        public static bool isPlaying => false;
        public static bool isEditor => false;
        public static bool isMobilePlatform => false;
        public static int targetFrameRate { get; set; }
        public static void Quit() { }
        public static void OpenURL(string url) { }
    }

    public static class PlayerPrefs
    {
        public static int GetInt(string k, int d) => d; public static int GetInt(string k) => 0;
        public static float GetFloat(string k, float d) => d; public static float GetFloat(string k) => 0;
        public static string GetString(string k, string d) => d; public static string GetString(string k) => "";
        public static void SetInt(string k, int v) { }
        public static void SetFloat(string k, float v) { }
        public static void SetString(string k, string v) { }
        public static bool HasKey(string k) => false;
        public static void DeleteKey(string k) { }
        public static void DeleteAll() { }
        public static void Save() { }
    }

    public static class Screen
    {
        public static int width => 1920;
        public static int height => 1080;
        public static float dpi => 96;
        public static Resolution currentResolution => new Resolution();
    }

    public static class Time
    {
        public static float time => 0;
        public static float deltaTime => 0.016f;
        public static float fixedDeltaTime => 0.02f;
        public static float unscaledDeltaTime => 0.016f;
        public static float timeScale { get; set; }
        public static float realtimeSinceStartup => 0;
        public static int frameCount => 0;
    }

    public static class Input
    {
        public static bool GetKeyDown(KeyCode k) => false;
        public static bool GetKeyUp(KeyCode k) => false;
        public static bool GetKey(KeyCode k) => false;
        public static bool GetMouseButtonDown(int b) => false;
        public static bool GetMouseButton(int b) => false;
        public static bool GetMouseButtonUp(int b) => false;
        public static Vector3 mousePosition => Vector3.zero;
        public static float GetAxis(string n) => 0;
        public static int touchCount => 0;
    }

    public static class Random
    {
        public static float value => 0;
        public static float Range(float min, float max) => min;
        public static int Range(int min, int max) => min;
    }

    public static class Resources
    {
        public static T Load<T>(string path) where T : Object => null;
        public static Object Load(string path) => null;
        public static T[] LoadAll<T>(string path) where T : Object => new T[0];
        public static void UnloadUnusedAssets() { }
    }

    // ─── Enums ───────────────────────────────────────────────
    public enum RuntimePlatform { WindowsPlayer, WindowsEditor, OSXPlayer, OSXEditor, LinuxPlayer, LinuxEditor, IPhonePlayer, Android, WebGLPlayer }
    public enum SystemLanguage { English, Chinese, ChineseSimplified, ChineseTraditional, Japanese, Korean, French, German, Spanish, Portuguese, Russian, Italian, Unknown }
    public enum KeyCode { None, Backspace, Tab, Return, Escape, Space, UpArrow, DownArrow, LeftArrow, RightArrow, A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q, R, S, T, U, V, W, X, Y, Z, Alpha0, Alpha1, Alpha2, Alpha3, Alpha4, Alpha5, Alpha6, Alpha7, Alpha8, Alpha9, Mouse0, Mouse1, Mouse2 }
    public enum TextAnchor { UpperLeft, UpperCenter, UpperRight, MiddleLeft, MiddleCenter, MiddleRight, LowerLeft, LowerCenter, LowerRight }
    public enum FontStyle { Normal, Bold, Italic, BoldAndItalic }
    public enum HorizontalWrapMode { Wrap, Overflow }
    public enum VerticalWrapMode { Truncate, Overflow }
    public enum Space { World, Self }
    public enum RuntimeInitializeLoadType { AfterSceneLoad, BeforeSceneLoad, AfterAssembliesLoaded, BeforeSplashScreen, SubsystemRegistration }
    public enum HideFlags { None = 0, HideInHierarchy = 1, HideInInspector = 2, DontSaveInEditor = 4, NotEditable = 8, DontSaveInBuild = 16, DontUnloadUnusedAsset = 32, DontSave = 52, HideAndDontSave = 61 }
    public enum SendMessageOptions { RequireReceiver, DontRequireReceiver }
    public enum LogType { Error = 0, Assert = 1, Warning = 2, Log = 3, Exception = 4 }
    public enum LogOption { None = 0, NoStacktrace = 1 }
    public enum SpriteMaskInteraction { None = 0, VisibleInsideMask = 1, VisibleOutsideMask = 2 }

    // ─── AnimationCurve ──────────────────────────────────────
    public class AnimationCurve
    {
        public float Evaluate(float t) => 0;
        public static AnimationCurve Linear(float ts, float vs, float te, float ve) => new AnimationCurve();
        public static AnimationCurve EaseInOut(float ts, float vs, float te, float ve) => new AnimationCurve();
    }
    public struct Keyframe { public float time, value; public Keyframe(float t, float v) { time = t; value = v; } }

    // ─── Async ───────────────────────────────────────────────
    public class AsyncOperation : YieldInstruction { public bool isDone => true; public float progress => 1; }

    // ─── Attributes ──────────────────────────────────────────
    [AttributeUsage(AttributeTargets.Field)] public class SerializeField : Attribute { }
    [AttributeUsage(AttributeTargets.Field)] public class HideInInspector : Attribute { }
    [AttributeUsage(AttributeTargets.Field)] public class HeaderAttribute : Attribute { public HeaderAttribute(string h) { } }
    [AttributeUsage(AttributeTargets.Field)] public class TooltipAttribute : Attribute { public TooltipAttribute(string t) { } }
    [AttributeUsage(AttributeTargets.Field)] public class RangeAttribute : Attribute { public RangeAttribute(float min, float max) { } }
    [AttributeUsage(AttributeTargets.Field)] public class SpaceAttribute : Attribute { public SpaceAttribute() { } public SpaceAttribute(float h) { } }
    [AttributeUsage(AttributeTargets.Field)] public class TextAreaAttribute : Attribute { public TextAreaAttribute() { } public TextAreaAttribute(int min, int max) { } }
    [AttributeUsage(AttributeTargets.Method)] public class RuntimeInitializeOnLoadMethodAttribute : Attribute { public RuntimeInitializeOnLoadMethodAttribute() { } public RuntimeInitializeOnLoadMethodAttribute(RuntimeInitializeLoadType t) { } }
    [AttributeUsage(AttributeTargets.Class)] public class RequireComponent : Attribute { public RequireComponent(Type t) { } }
    [AttributeUsage(AttributeTargets.Class)] public class DisallowMultipleComponent : Attribute { }
    [AttributeUsage(AttributeTargets.Class | AttributeTargets.Method)] public class AddComponentMenu : Attribute { public AddComponentMenu(string n) { } }
    [AttributeUsage(AttributeTargets.Class)] public class ExecuteInEditMode : Attribute { }
    [AttributeUsage(AttributeTargets.Class)] public class ExecuteAlways : Attribute { }
    [AttributeUsage(AttributeTargets.Class | AttributeTargets.Struct)] public class SerializableAttribute : Attribute { }

    // ─── RectOffset ──────────────────────────────────────────
    public class RectOffset
    {
        public int left { get; set; } public int right { get; set; } public int top { get; set; } public int bottom { get; set; }
        public RectOffset() { }
        public RectOffset(int l, int r, int t, int b) { left = l; right = r; top = t; bottom = b; }
    }

    // ─── Audio ───────────────────────────────────────────────
    public class AudioSource : Behaviour
    {
        public AudioClip clip { get; set; }
        public float volume { get; set; }
        public float pitch { get; set; }
        public bool loop { get; set; }
        public bool isPlaying => false;
        public void Play() { } public void Stop() { } public void Pause() { }
    }
    public class AudioClip : Object { public float length => 0; public int samples => 0; public int channels => 1; public int frequency => 44100; }

    // ─── Animation ───────────────────────────────────────────
    public class Animator : Behaviour
    {
        public void Play(string s) { } public void Play(string s, int l) { }
        public void SetTrigger(string n) { } public void SetBool(string n, bool v) { }
        public void SetFloat(string n, float v) { } public void SetInteger(string n, int v) { }
        public float GetFloat(string n) => 0; public int GetInteger(string n) => 0; public bool GetBool(string n) => false;
        public void ResetTrigger(string n) { }
        public float speed { get; set; }
    }
    public class Animation : Behaviour { public void Play() { } public void Play(string a) { } public void Stop() { } }

    // ─── Physics stubs (in CoreModule) ───────────────────────
    public class Rigidbody2D : Component { public Vector2 velocity { get; set; } public float gravityScale { get; set; } }
    public class Collider2D : Behaviour { }
    public class BoxCollider2D : Collider2D { }
    public class CircleCollider2D : Collider2D { }
    public class Collider : Behaviour { }
    public class BoxCollider : Collider { }
    public struct RaycastHit2D { public Vector2 point; public float distance; public Collider2D collider; }
    public static class Physics2D { public static RaycastHit2D Raycast(Vector2 o, Vector2 d) => new RaycastHit2D(); }

    // ─── Events namespace ────────────────────────────────────
    namespace Events
    {
        public class UnityEvent { public void Invoke() { } public void AddListener(UnityAction c) { } public void RemoveListener(UnityAction c) { } public void RemoveAllListeners() { } }
        public class UnityEvent<T0> { public void Invoke(T0 a) { } public void AddListener(UnityAction<T0> c) { } public void RemoveListener(UnityAction<T0> c) { } }
        public class UnityEvent<T0, T1> { public void Invoke(T0 a, T1 b) { } }
        public delegate void UnityAction();
        public delegate void UnityAction<T0>(T0 a);
        public delegate void UnityAction<T0, T1>(T0 a, T1 b);
    }

    // ─── EventSystems ────────────────────────────────────────
    namespace EventSystems
    {
        public class EventSystem : MonoBehaviour { }
        public class PointerEventData { public Vector2 position; }
        public class BaseEventData { }
        public interface IPointerClickHandler { void OnPointerClick(PointerEventData e); }
        public interface IPointerEnterHandler { void OnPointerEnter(PointerEventData e); }
        public interface IPointerExitHandler { void OnPointerExit(PointerEventData e); }
        public interface IPointerDownHandler { void OnPointerDown(PointerEventData e); }
        public interface IPointerUpHandler { void OnPointerUp(PointerEventData e); }
        public interface IDragHandler { void OnDrag(PointerEventData e); }
        public interface IBeginDragHandler { void OnBeginDrag(PointerEventData e); }
        public interface IEndDragHandler { void OnEndDrag(PointerEventData e); }
        public interface IScrollHandler { void OnScroll(PointerEventData e); }
        public class UIBehaviour : MonoBehaviour { }
        public abstract class BaseRaycaster : UIBehaviour { }
    }

    // ─── SceneManagement ─────────────────────────────────────
    namespace SceneManagement
    {
        public struct Scene { public string name; public int buildIndex; public bool isLoaded; }
        public static class SceneManager
        {
            public static Scene GetActiveScene() => new Scene();
            public static AsyncOperation LoadSceneAsync(string n) => new AsyncOperation();
            public static AsyncOperation LoadSceneAsync(int i) => new AsyncOperation();
        }
    }

    // ─── Networking ──────────────────────────────────────────
    namespace Networking
    {
        public class UnityWebRequest : IDisposable
        {
            public string url { get; set; }
            public bool isDone => true;
            public string error => "";
            public DownloadHandler downloadHandler { get; set; }
            public void Dispose() { }
            public static UnityWebRequest Get(string uri) => new UnityWebRequest();
            public UnityWebRequestAsyncOperation SendWebRequest() => new UnityWebRequestAsyncOperation();
        }
        public class DownloadHandler { public string text => ""; public byte[] data => new byte[0]; }
        public class DownloadHandlerBuffer : DownloadHandler { }
        public class UnityWebRequestAsyncOperation : AsyncOperation { }
    }

    // ─── Serialization ──────────────────────────────────────
    public interface ISerializationCallbackReceiver
    {
        void OnBeforeSerialize();
        void OnAfterDeserialize();
    }
}

namespace Unity.Profiling
{
    public struct ProfilerMarker
    {
        public ProfilerMarker(string name) { }
        public void Begin() { }
        public void End() { }
        public AutoScope Auto() => default;
        public struct AutoScope : System.IDisposable { public void Dispose() { } }
    }
}
