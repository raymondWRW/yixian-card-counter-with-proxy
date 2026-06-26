// UnityEngine.UI facade — Text, Image, Button, etc.
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.EventSystems;

namespace UnityEngine.UI
{
    public class Graphic : UIBehaviour
    {
        public Color color { get; set; }
        public Material material { get; set; }
        public RectTransform rectTransform { get; set; } = new RectTransform();
        public Canvas canvas => null;
        public bool raycastTarget { get; set; }
        public virtual void CrossFadeAlpha(float a, float d, bool i) { }
        public virtual void CrossFadeColor(Color c, float d, bool i, bool u) { }
    }
    public class MaskableGraphic : Graphic { public bool maskable { get; set; } }
    public class Text : MaskableGraphic
    {
        public string text { get; set; }
        public Font font { get; set; }
        public int fontSize { get; set; }
        public FontStyle fontStyle { get; set; }
        public TextAnchor alignment { get; set; }
        public HorizontalWrapMode horizontalOverflow { get; set; }
        public VerticalWrapMode verticalOverflow { get; set; }
        public float lineSpacing { get; set; }
        public bool supportRichText { get; set; }
        public bool resizeTextForBestFit { get; set; }
    }
    public class Image : MaskableGraphic
    {
        public Sprite sprite { get; set; }
        public Sprite overrideSprite { get; set; }
        public Image.Type type { get; set; }
        public float fillAmount { get; set; }
        public bool preserveAspect { get; set; }
        public enum Type { Simple, Sliced, Tiled, Filled }
        public enum FillMethod { Horizontal, Vertical, Radial90, Radial180, Radial360 }
        public FillMethod fillMethod { get; set; }
        public bool fillClockwise { get; set; }
        public int fillOrigin { get; set; }
        public void SetNativeSize() { }
    }
    public class RawImage : MaskableGraphic { public Texture texture { get; set; } public Rect uvRect { get; set; } }
    public class Button : Selectable { public ButtonClickedEvent onClick { get; set; } public class ButtonClickedEvent : UnityEvent { } }
    public class Toggle : Selectable { public bool isOn { get; set; } public ToggleEvent onValueChanged { get; set; } public ToggleGroup group { get; set; } public class ToggleEvent : UnityEvent<bool> { } }
    public class ToggleGroup : MonoBehaviour { public bool allowSwitchOff { get; set; } }
    public class Slider : Selectable { public float value { get; set; } public float minValue { get; set; } public float maxValue { get; set; } public bool wholeNumbers { get; set; } public SliderEvent onValueChanged { get; set; } public class SliderEvent : UnityEvent<float> { } }
    public class Scrollbar : Selectable { public float value { get; set; } public float size { get; set; } public int numberOfSteps { get; set; } }
    public class ScrollRect : UIBehaviour
    {
        public RectTransform content { get; set; }
        public bool horizontal { get; set; }
        public bool vertical { get; set; }
        public Vector2 normalizedPosition { get; set; }
        public float verticalNormalizedPosition { get; set; }
        public float horizontalNormalizedPosition { get; set; }
    }
    public class InputField : Selectable
    {
        public string text { get; set; }
        public int characterLimit { get; set; }
        public ContentType contentType { get; set; }
        public Text textComponent { get; set; }
        public Text placeholder { get; set; }
        public OnChangeEvent onValueChanged { get; set; }
        public SubmitEvent onEndEdit { get; set; }
        public enum ContentType { Standard, Autocorrected, IntegerNumber, DecimalNumber, Alphanumeric, Name, EmailAddress, Password, Pin, Custom }
        public class OnChangeEvent : UnityEvent<string> { }
        public class SubmitEvent : UnityEvent<string> { }
    }
    public class Dropdown : Selectable
    {
        public int value { get; set; }
        public List<OptionData> options { get; set; }
        public DropdownEvent onValueChanged { get; set; }
        public class OptionData { public string text { get; set; } public Sprite image { get; set; } public OptionData() { } public OptionData(string t) { text = t; } }
        public class DropdownEvent : UnityEvent<int> { }
    }
    public class Selectable : UIBehaviour { public bool interactable { get; set; } public Graphic targetGraphic { get; set; } }
    public class Mask : MonoBehaviour { public bool showMaskGraphic { get; set; } }
    public class RectMask2D : UIBehaviour { }
    public class LayoutElement : UIBehaviour { public float minWidth { get; set; } public float minHeight { get; set; } public float preferredWidth { get; set; } public float preferredHeight { get; set; } public float flexibleWidth { get; set; } public float flexibleHeight { get; set; } public bool ignoreLayout { get; set; } }
    public abstract class LayoutGroup : UIBehaviour { public RectOffset padding { get; set; } public TextAnchor childAlignment { get; set; } }
    public class HorizontalLayoutGroup : LayoutGroup { }
    public class VerticalLayoutGroup : LayoutGroup { }
    public class GridLayoutGroup : LayoutGroup { public Vector2 cellSize { get; set; } public Vector2 spacing { get; set; } }
    public class ContentSizeFitter : UIBehaviour { public FitMode horizontalFit { get; set; } public FitMode verticalFit { get; set; } public enum FitMode { Unconstrained, MinSize, PreferredSize } }
    public class CanvasScaler : UIBehaviour { public ScaleMode uiScaleMode { get; set; } public Vector2 referenceResolution { get; set; } public float matchWidthOrHeight { get; set; } public enum ScaleMode { ConstantPixelSize, ScaleWithScreenSize, ConstantPhysicalSize } }
    public class GraphicRaycaster : BaseRaycaster { }
    public static class LayoutRebuilder { public static void ForceRebuildLayoutImmediate(RectTransform r) { } }
}

namespace UnityEngine.EventSystems
{
    public struct RaycastResult { public float distance; public int sortingLayer; public int sortingOrder; }
}
public class LongPressedEventTrigger : UnityEngine.MonoBehaviour {}
namespace UnityEngine.UI.Extensions { public class Gradient2 : UnityEngine.MonoBehaviour {} }
