// OracleAnim — animation/visual EVENT CAPTURE for the web battle viewer.
//
// The headless oracle runs combat with visuals INERT (nopped) for bit-exact parity. But the in-browser
// battle viewer needs to REPLAY those battles with real animations — and the visual methods we nop are
// exactly the animation events it needs (cast, hurt, damage/heal popups, card flip, ...). So the same real
// game run can ALSO emit a structured per-turn animation-event stream: parity wants visuals inert, the viewer
// wants them recorded; serve both from one run.
//
// DllPatcher.PatchAnimationCaptureModule (gated by env ORACLE_CAPTURE_ANIM=1, so normal parity runs are
// untouched) injects `OracleAnim.Record(<turn>, "<Type.Method>")` at the start of each visual/animation
// method — even when that method is nopped (we capture the INTENT, not the rendered pixels). The turn comes
// from BattleExecuter.s_OracleHuiHe (exposed by PatchExposeHuiHe). Events are emitted as one JSON line each,
// prefixed `ANIM `, on stdout (or appended to the file in ORACLE_CAPTURE_ANIM_FILE) for the viewer pipeline
// to map onto Spine animation states (see memory-bank/docs/oracle-consolidation-charter.md).
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;

namespace YiXianOracle;

public static class OracleAnim
{
    public static readonly bool Enabled = Environment.GetEnvironmentVariable("ORACLE_CAPTURE_ANIM") == "1";
    static readonly string? File_ = Environment.GetEnvironmentVariable("ORACLE_CAPTURE_ANIM_FILE");
    const BindingFlags ANY = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

    // Called from injected IL at the start of each animation/visual/gameplay-numeric method.
    // `ev` = "DeclaringType.Method"; a0/a1 = the method's first two int-like args (ModifyHp delta, Attack
    // atk/count, ...) or 0; `actor` = the method's `this` (a BattleCharacter etc.). We resolve actor.animator
    // .charId (already seeded by the oracle's animator factory) so the viewer knows WHICH character acted —
    // 0 when unknown (UI/card objects have no animator). Reflection is fine here: capture is gated + offline.
    public static void Record(int turn, string ev, int a0, int a1, object actor)
    {
        if (!Enabled) return;
        try
        {
            var line = $"ANIM {{\"turn\":{turn},\"ev\":\"{ev}\",\"a0\":{a0},\"a1\":{a1},\"actor\":{CharId(actor)},\"card\":{CardId(actor)}}}";
            if (File_ != null) File.AppendAllText(File_, line + "\n");
            else Console.WriteLine(line);
        }
        catch { /* capture must never break combat */ }
    }

    static object? Get(object? o, string name)
    {
        if (o == null) return null;
        var t = o.GetType();
        return t.GetField(name, ANY)?.GetValue(o) ?? t.GetProperty(name, ANY)?.GetValue(o);
    }

    // Resolve which character acted. Primary: the RECORD-derived id (always present in combat) —
    // battleTempData.playerData.publicData.characterId. Fallback: the seeded animator.charId. 0 if neither
    // (UI/card objects that aren't a BattleCharacter). Field-or-property at each hop (game uses both).
    static int CharId(object? actor)
    {
        if (actor == null) return 0;
        try
        {
            var pub = Get(Get(Get(actor, "battleTempData"), "playerData"), "publicData");
            var cid = Get(pub, "characterId");
            if (cid != null) return Convert.ToInt32(cid);
            var ac = Get(Get(actor, "animator"), "charId");
            return ac != null ? Convert.ToInt32(ac) : 0;
        }
        catch { return 0; }
    }

    // For CardItem.* events: which card's animation fired (cardConfig.id). 0 for non-card actors.
    static int CardId(object? actor)
    {
        try { var id = Get(Get(actor, "cardConfig"), "id"); return id != null ? Convert.ToInt32(id) : 0; }
        catch { return 0; }
    }
}
