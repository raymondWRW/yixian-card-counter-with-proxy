using System;
using System.Collections.Generic;
using UnityEngine;
using TMPro;
using UniRx;
using Proto;

namespace YiXianBot
{
    // Per-card overlay, no top panel:
    //  · board card top:  "配置攻击(边际贡献)"  e.g. 12(42)  — config from bot, marginal pushed (yisim).
    //  · every card top-right: 剩X (counter.remaining() by NAME).
    // 8-layer manual outline (font-agnostic). Parented to movableRT (scales on hover).
    public static class Hud23
    {
        const string DMG = "BotDmg";
        const string LEFT = "BotLeft";
        static readonly Vector2[] OFF = {
            new Vector2(2,0), new Vector2(-2,0), new Vector2(0,2), new Vector2(0,-2),
            new Vector2(2,2), new Vector2(-2,2), new Vector2(2,-2), new Vector2(-2,-2)
        };
        static IDisposable s_sub;
        static int s_noCard = 0;     // consecutive ticks with no visible card (battle debounce)
        static TMP_FontAsset s_font;
        static Dictionary<string, int> s_remaining = new Dictionary<string, int>();   // by card name
        static bool s_showLeft = true;   // 记牌器 剩X toggle
        static Dictionary<int, int> s_marginal = new Dictionary<int, int>();           // by board slot index
        static float s_dmgY = -2f;   // damage label Y (on the card top, below the prepare bar)
        static string s_total = "";  // whole-board total damage (yisim), screen-anchored
        static GameObject s_totalGo;
        static List<TextMeshProUGUI> s_totalLayers;
        static string s_opp = "";    // opponent HP cap + 修为 (top-left, by 生命上限)
        static GameObject s_oppGo;
        static List<TextMeshProUGUI> s_oppLayers;
        static string s_warn = "";   // danger-card warning (flashes)
        static GameObject s_warnGo;
        static List<TextMeshProUGUI> s_warnLayers;
        // Anchored positions (runtime-tunable via SetPos so we needn't recompile).
        static Vector2 s_totalPos = new Vector2(0f, -182f);   // T1..T8 (top-center)
        static Vector2 s_warnPos = new Vector2(0f, -222f);    // danger warning
        static Vector2 s_oppPos = new Vector2(70f, -240f);    // opponent 命/修 (top-left)
        static readonly Color s_black = new Color(0f, 0f, 0f, 1f);

        public static string Show()
        {
            try {
                if (s_sub != null) return "ok:already";
                s_sub = ObservableExtensions.Subscribe(
                    Observable.Interval(TimeSpan.FromSeconds(0.5), Scheduler.MainThreadIgnoreTimeScale),
                    new Action<long>(OnTick));
                return "ok:subscribed";
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string Hide()
        {
            try {
                if (s_sub != null) { s_sub.Dispose(); s_sub = null; }
                foreach (var o in UnityEngine.Object.FindObjectsOfType(typeof(GameObject)))
                {
                    var g = o as GameObject;
                    if (g != null && (g.name == DMG || g.name == LEFT || g.name == "BotTotal"
                        || g.name == "BotOpp" || g.name == "BotWarn")) UnityEngine.Object.Destroy(g);
                }
                s_totalGo = null; s_totalLayers = null;
                s_oppGo = null; s_oppLayers = null; s_warnGo = null; s_warnLayers = null;
                return "ok:hidden";
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string SetRemaining(string data)   // "卡名:剩数|卡名:剩数"
        {
            try {
                var d = new Dictionary<string, int>();
                if (!string.IsNullOrEmpty(data))
                    foreach (var part in data.Split('|'))
                    { int idx = part.LastIndexOf(':'); if (idx > 0) { int c; if (int.TryParse(part.Substring(idx + 1), out c)) d[part.Substring(0, idx)] = c; } }
                s_remaining = d; return "ok:" + d.Count;
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string SetDmgY(string y) { float v; if (float.TryParse(y, out v)) s_dmgY = v; return "ok:" + s_dmgY; }
        public static string SetTotal(string s) { s_total = s ?? ""; return "ok:" + s_total; }
        public static string SetOpponent(string s) { s_opp = s ?? ""; return "ok:" + s_opp; }
        public static string SetShowLeft(string v) { s_showLeft = (v == "1" || v == "true"); return "ok:" + s_showLeft; }
        public static string SetWarning(string s) { s_warn = s ?? ""; return "ok:" + s_warn; }
        // Runtime position tuning: SetPos("total,0,-132") / "warn,..." / "opp,...".
        public static string SetPos(string data)
        {
            try {
                var p = (data ?? "").Split(',');
                if (p.Length != 3) return "bad";
                float fx, fy;
                if (!float.TryParse(p[1], out fx) || !float.TryParse(p[2], out fy)) return "badnum";
                var v = new Vector2(fx, fy);
                if (p[0] == "total") s_totalPos = v;
                else if (p[0] == "warn") s_warnPos = v;
                else if (p[0] == "opp") s_oppPos = v;
                else return "no:" + p[0];
                return "ok:" + p[0] + " " + fx + "," + fy;
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string SetMarginal(string data)     // "slot:值|slot:值"
        {
            try {
                var d = new Dictionary<int, int>();
                if (!string.IsNullOrEmpty(data))
                    foreach (var part in data.Split('|'))
                    { var kv = part.Split(':'); int s, v; if (kv.Length == 2 && int.TryParse(kv[0], out s) && int.TryParse(kv[1], out v)) d[s] = v; }
                s_marginal = d; return "ok:" + d.Count;
            } catch (Exception e) { return "EX:" + e.Message; }
        }

        static bool HasCJK(string s)
        { if (string.IsNullOrEmpty(s)) return false; for (int i = 0; i < s.Length; i++) { char c = s[i]; if (c >= 0x4E00 && c <= 0x9FFF) return true; } return false; }
        static TMP_FontAsset FindFont()
        {
            if (s_font != null) return s_font; TMP_FontAsset fb = null;
            foreach (var o in UnityEngine.Object.FindObjectsOfType(typeof(TextMeshProUGUI)))
            { var t = o as TextMeshProUGUI; if (t == null || t.font == null) continue; if (fb == null) fb = t.font; if (HasCJK(t.text)) { s_font = t.font; return s_font; } }
            s_font = fb; return s_font;
        }
        static TextMeshProUGUI MakeLayer(Transform c, float size, Color col, Vector2 off)
        {
            var go = new GameObject(off == Vector2.zero ? "fg" : "o"); go.transform.SetParent(c, false);
            var lbl = go.AddComponent(typeof(TextMeshProUGUI)) as TextMeshProUGUI;
            var f = FindFont(); if (f != null) lbl.font = f;
            lbl.fontSize = size; lbl.color = col; lbl.alignment = TextAlignmentOptions.Center;
            lbl.raycastTarget = false; lbl.enableWordWrapping = false;
            var rt = lbl.rectTransform; rt.anchorMin = Vector2.zero; rt.anchorMax = Vector2.one; rt.offsetMin = off; rt.offsetMax = off;
            return lbl;
        }
        static List<TextMeshProUGUI> Ensure(Transform vis, string tag, bool isLeft)
        {
            var ex = vis.Find(tag); var list = new List<TextMeshProUGUI>();
            if (ex != null) { for (int i = 0; i < ex.childCount; i++) { var t = ex.GetChild(i).GetComponent(typeof(TextMeshProUGUI)) as TextMeshProUGUI; if (t != null) list.Add(t); } return list; }
            var c = new GameObject(tag); c.transform.SetParent(vis, false);
            var crt = c.AddComponent(typeof(RectTransform)) as RectTransform;
            float size; Color col; Color black = new Color(0f, 0f, 0f, 1f);
            if (isLeft)
            {
                size = 26f; col = new Color(0.62f, 0.93f, 1f, 1f);
                crt.anchorMin = new Vector2(1f, 1f); crt.anchorMax = new Vector2(1f, 1f); crt.pivot = new Vector2(1f, 1f);
                crt.anchoredPosition = new Vector2(1f, -18f); crt.sizeDelta = new Vector2(72f, 38f);
            }
            else
            {
                size = 26f; col = new Color(1f, 0.88f, 0.42f, 1f);
                crt.anchorMin = new Vector2(0.5f, 1f); crt.anchorMax = new Vector2(0.5f, 1f); crt.pivot = new Vector2(0.5f, 1f);
                crt.anchoredPosition = new Vector2(0f, s_dmgY); crt.sizeDelta = new Vector2(120f, 34f);
            }
            for (int i = 0; i < OFF.Length; i++) list.Add(MakeLayer(c.transform, size, black, OFF[i]));
            list.Add(MakeLayer(c.transform, size, col, Vector2.zero));
            return list;
        }
        static void RemoveDmg(Transform vis) { var d = vis.Find(DMG); if (d != null) UnityEngine.Object.Destroy(((Component)d).gameObject); }
        static void SetText(List<TextMeshProUGUI> list, string txt) { for (int k = 0; k < list.Count; k++) list[k].text = txt; }
        static void ApplyPos(GameObject go, Vector2 pos)
        {
            if (go == null) return;
            var rt = go.GetComponent(typeof(RectTransform)) as RectTransform;
            if (rt != null && rt.anchoredPosition != pos) rt.anchoredPosition = pos;
        }

        // Create a screen-anchored 8-layer-outlined label under the root canvas.
        static GameObject MakeScreenLabel(string nm, Vector2 anchor, Vector2 pivot,
            Vector2 pos, Vector2 size, float fsize, Color col, out List<TextMeshProUGUI> layers)
        {
            layers = null;
            Canvas canv = null;
            foreach (var o in UnityEngine.Object.FindObjectsOfType(typeof(Canvas)))
            { var c = o as Canvas; if (c != null) { canv = c; if (c.transform.parent == null) break; } }
            if (canv == null) return null;
            var go = new GameObject(nm);
            go.transform.SetParent(canv.transform, false);
            var crt = go.AddComponent(typeof(RectTransform)) as RectTransform;
            crt.anchorMin = anchor; crt.anchorMax = anchor; crt.pivot = pivot;
            crt.anchoredPosition = pos; crt.sizeDelta = size;
            layers = new List<TextMeshProUGUI>();
            for (int i = 0; i < OFF.Length; i++) layers.Add(MakeLayer(go.transform, fsize, s_black, OFF[i]));
            layers.Add(MakeLayer(go.transform, fsize, col, Vector2.zero));
            return go;
        }

        static void DrawTotal()
        {
            if (string.IsNullOrEmpty(s_total)) { if (s_totalGo != null) s_totalGo.SetActive(false); return; }
            if (s_totalGo == null)
                s_totalGo = MakeScreenLabel("BotTotal", new Vector2(0.5f, 1f), new Vector2(0.5f, 1f),
                    s_totalPos, new Vector2(1180f, 44f), 26f, new Color(1f, 0.85f, 0.35f, 1f), out s_totalLayers);
            if (s_totalGo == null) return;
            s_totalGo.SetActive(true); ApplyPos(s_totalGo, s_totalPos); SetText(s_totalLayers, s_total);
        }

        static void DrawOpp()
        {
            if (string.IsNullOrEmpty(s_opp)) { if (s_oppGo != null) s_oppGo.SetActive(false); return; }
            if (s_oppGo == null)
                s_oppGo = MakeScreenLabel("BotOpp", new Vector2(0f, 1f), new Vector2(0f, 1f),
                    s_oppPos, new Vector2(380f, 40f), 24f, new Color(1f, 0.62f, 0.62f, 1f), out s_oppLayers);
            if (s_oppGo == null) return;
            s_oppGo.SetActive(true); ApplyPos(s_oppGo, s_oppPos); SetText(s_oppLayers, s_opp);
        }

        // Flashing danger warning (toggles visibility each tick ≈ 0.5s).
        static void DrawWarn(long n)
        {
            if (string.IsNullOrEmpty(s_warn)) { if (s_warnGo != null) s_warnGo.SetActive(false); return; }
            if (s_warnGo == null)
                s_warnGo = MakeScreenLabel("BotWarn", new Vector2(0.5f, 1f), new Vector2(0.5f, 1f),
                    s_warnPos, new Vector2(1000f, 48f), 32f, new Color(1f, 0.22f, 0.22f, 1f), out s_warnLayers);
            if (s_warnGo == null) return;
            ApplyPos(s_warnGo, s_warnPos);
            s_warnGo.SetActive((n % 2) == 0);
            SetText(s_warnLayers, s_warn);
        }

        static void HideScreen()
        {
            if (s_totalGo != null) s_totalGo.SetActive(false);
            if (s_oppGo != null) s_oppGo.SetActive(false);
            if (s_warnGo != null) s_warnGo.SetActive(false);
        }

        static void OnTick(long n)
        {
            try {
                var bp = ILRPanelBase.FindILRPanel<BattlePanel>();
                var cp = bp != null ? bp.FindILRSubPanel<CardPanel>() : null;
                if (cp == null) { HideScreen(); return; }   // out of a game → hide all screen labels

                // Count cards actually rendered on the placement board/hand. In
                // battle the placement cards aren't shown (only the battle arena),
                // so visible==0 ⇒ we're NOT in placement ⇒ hide the screen overlays.
                int visible = 0;
                var grids = cp.GetCardGrids();
                for (int i = 0; i < grids.Count; i++)
                {
                    var card = grids[i].GetCard();
                    if (card == null || card.cardConfig == null) continue;
                    var vis = card.movableRT; if (vis == null) continue;
                    if (vis.gameObject.activeInHierarchy) visible++;
                    // Per-card damage removed (user wants the whole-board total via
                    // DrawTotal). Keep only the deck-count (剩X) on each board card.
                    RemoveDmg(vis);
                    SetText(Ensure(vis, LEFT, true), LeftTxt(card.cardConfig.name));
                }
                var hand = cp.GetHandCards();
                for (int i = 0; i < hand.Count; i++)
                {
                    var card = hand[i];
                    if (card == null || card.cardConfig == null) continue;
                    var vis = card.movableRT; if (vis == null) continue;
                    if (vis.gameObject.activeInHierarchy) visible++;
                    RemoveDmg(vis);
                    SetText(Ensure(vis, LEFT, true), LeftTxt(card.cardConfig.name));
                }
                // Debounce: only hide after SUSTAINED no-visible-cards (~2s), so a
                // single-frame dip during placement animations doesn't flicker the
                // overlays. Battle lasts many seconds, so a 2s delay is invisible.
                if (visible == 0) s_noCard++; else s_noCard = 0;
                if (s_noCard >= 4) { HideScreen(); return; }   // sustained → in battle
                DrawTotal();
                DrawOpp();
                DrawWarn(n);
            } catch (Exception) { }
        }
        static string LeftTxt(string name)
        { if (!s_showLeft) return ""; int left; return s_remaining.TryGetValue(name ?? "", out left) ? ("剩" + left) : "剩?"; }
    }
}
