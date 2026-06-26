// Unity.TextMeshPro facade
using UnityEngine;
using UnityEngine.UI;

namespace TMPro
{
    public class TMP_Text : MaskableGraphic
    {
        public string text { get; set; }
        public float fontSize { get; set; }
        public new Color color { get; set; }
        public TextAlignmentOptions alignment { get; set; }
        public bool enableWordWrapping { get; set; }
        public TextOverflowModes overflowMode { get; set; }
        public float alpha { get; set; }
        public FontStyles fontStyle { get; set; }
        public new RectTransform rectTransform { get; set; } = new RectTransform();
    }
    [System.Flags]
    public enum FontStyles { Normal = 0, Bold = 1, Italic = 2, Underline = 4, LowerCase = 8, UpperCase = 16, SmallCaps = 32, Strikethrough = 64, Superscript = 128, Subscript = 256, Highlight = 512 }
    public class TextMeshPro : TMP_Text { }
    public class TextMeshProUGUI : TMP_Text { }
    public class TMP_InputField : UnityEngine.EventSystems.UIBehaviour { public string text { get; set; } public int characterLimit { get; set; } }
    public class TMP_Dropdown : UnityEngine.EventSystems.UIBehaviour { public int value { get; set; } public System.Collections.Generic.List<OptionData> options { get; set; } public class OptionData { public string text { get; set; } public OptionData() { } public OptionData(string t) { text = t; } } }
    public enum TextAlignmentOptions { TopLeft, Top, TopRight, Left, Center, Right, BottomLeft, Bottom, BottomRight, MidlineLeft, Midline, MidlineRight }
    public enum TextOverflowModes { Overflow, Ellipsis, Masking, Truncate, ScrollRect, Page, Linked }
    public class TMP_SpriteAsset : ScriptableObject { }
    public class TMP_FontAsset : ScriptableObject { }
    public class TMP_Settings : ScriptableObject { }
}
