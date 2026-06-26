// DarkSun.UI facade
using System;
using UnityEngine;

namespace DarkSun.UI
{
    public class UIPanel : MonoBehaviour { public virtual void OnOpen(params object[] args) { } public virtual void OnClose() { } public virtual void OnRefresh() { } public bool IsOpen { get; set; } public void Close() { } public void Open(params object[] args) { } }
    public class UIWindow : UIPanel { public string WindowName { get; set; } }
    public class UIWidget : MonoBehaviour { public virtual void Init() { } public virtual void Refresh() { } }
    public class UIManager : MonoBehaviour { public static UIManager Instance { get; set; } public T GetPanel<T>() where T : UIPanel => null; public T OpenPanel<T>(params object[] args) where T : UIPanel => null; public void ClosePanel<T>() where T : UIPanel { } public void CloseAll() { } public static RectTransform rootPanel { get; set; } = new RectTransform(); public static Camera worldCamera { get; set; } }
    public class UIButton : MonoBehaviour { public event Action OnClick; public bool Interactable { get; set; } }
    public class UIText : MonoBehaviour { public string Text { get; set; } }
    public class UIImage : MonoBehaviour { public Sprite Sprite { get; set; } public Color Color { get; set; } public float FillAmount { get; set; } }
    public class UIToggle : MonoBehaviour { public bool IsOn { get; set; } public event Action<bool> OnValueChanged; }
    public class UISlider : MonoBehaviour { public float Value { get; set; } public event Action<float> OnValueChanged; }
    public class UIPopup : UIPanel { }
    public class UITip : MonoBehaviour { public static void Show(string t) { } public static void Show(string t, float d) { } }
    public class UIEffect : MonoBehaviour { public virtual void Play() { } public virtual void Stop() { } }
    public enum MessageBoxType { None, OK, YesNo, OKCancel }
    public class UIPanelBase : UIPanel { }
    public class LoadingPanel : UIPanel { public static void Show() { } public static void Hide() { } }
    public class SceneLoader { public static bool isLoading { get; set; } public static string currentSceneName { get; set; } = "Battle"; public static void Load(string s) { } public static void LoadAsync(string s, System.Action cb = null) { } }
}

// Types referenced from game DLL without namespace qualifiers
public enum MessageBoxType { None, OK, YesNo, OKCancel }
public class UIPanelBase : DarkSun.UI.UIPanel { }
public class LoadingPanel : DarkSun.UI.UIPanel { public static new void Show() { } public static new void Hide() { } }
public class SceneLoader { public static bool isLoading { get; set; } public static string currentSceneName { get; set; } = "Battle"; public static void Load(string s) { } public static void LoadAsync(string s, System.Action cb = null) { } }
public class UIManager : UnityEngine.MonoBehaviour
{
    public static UIManager Instance { get; set; }
    public T GetPanel<T>() where T : class => null;
    public T OpenPanel<T>(params object[] args) where T : class => null;
    public void ClosePanel<T>() where T : class { }
    public void CloseAll() { }
    public UnityEngine.Transform uiCanvas => null;
    public static UnityEngine.RectTransform rootPanel { get; set; } = new UnityEngine.RectTransform();
    public static UnityEngine.Camera worldCamera { get; set; }
}
