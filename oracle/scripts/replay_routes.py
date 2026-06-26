#!/usr/bin/env python3
"""
replay_routes.py — assemble a structured BATTLE REPLAY from one oracle run, for the web battle viewer.

Owner: Agent 1 (battle viewer). Mounted into fixture_editor_server.py by Agent 2 (server owner) via:
    from replay_routes import router as replay_router; app.include_router(replay_router)

The oracle, run with env ORACLE_CAPTURE_ANIM=1, prints (besides the normal `{"engine":...}` result line) one
`ANIM {...}` JSON line per visual/animation method call — the game's OWN per-turn per-character animation intent:
    ANIM {"turn":1,"ev":"BattleCharacter.Cast","a0":2,"a1":0,"actor":4000004,"card":0}
We turn that + the combat log + the character spine assets into ONE `Replay` object the client plays back with
accurate, turn-gated timing (clip durations come from the loaded .skel client-side).

Replay shape (the client contract):
  {
    "left": Actor, "right": Actor,            # Actor = {charId, side, name, spine:{skel/atlas/png urls,...}, animGroups}
    "turns": [ {"index": int, "events": [Event, ...]} ],
    "result": {"turns": int, "leftHp": int, "rightHp": int, "hpDelta": int, "expected": {...}},
  }
  Event = {"actor": charId, "side": "L"|"R", "kind": str, "group": str|None, "a0": int, "a1": int, "card": int}
    kind ∈ cast | attack | hurt | modifyHp | modifyDef | modifyAnima | moveTo | death | demon
          | cardShow | cardReturn | cardFlip | other
    group = the Spine animation-group key the client picks a clip from (idle/attack/cast/hurt/death/...), or None.

Standalone test:  uv run python tools/game-oracle/scripts/replay_routes.py data/fixtures/dv90m3g-r12.json
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ORACLE_DLL = ROOT / "tools" / "game-oracle" / "Oracle" / "bin" / "Release" / "net8.0" / "Oracle.dll"
BATTLE_ASSETS = ROOT / "data" / "game" / "battle_assets.json"

# ANIM event method -> (kind, spine animation-group the client animates). group=None => no character animation
# (a bar/number change only). Attack/Cast/Hurt/Death map to the character's lifecycle clip groups.
_EV_MAP = {
    "BattleCharacter.Cast":            ("cast",        "cast"),
    "BattleCharacter.Attack":          ("attack",      "attack"),
    "BattleCharacter.ModifyHp":        ("modifyHp",    None),     # delta a0; if <0 the actor is the one HURT
    "BattleCharacter.ModifyHpWithFx":  ("modifyHp",    None),     # same HP delta with a hit fx — must hit the bar
    "BattleCharacter.ModifyMaxHp":     ("modifyMaxHp", None),
    "BattleCharacter.ModifyDef":       ("modifyDef",   None),
    "BattleCharacter.ModifyAnima":     ("modifyAnima", None),     # Qi
    "BattleCharacter.ModifyTempLife":  ("modifyTempLife", None),
    "BattleCharacter.MoveTo":          ("moveTo",      None),
    "BattleCharacter.ShowDeathDamage": ("death",       "death"),
    "BattleCharacter.OnBattleLose":    ("death",       "death"),
    "BattleCharacter.EnableDemonEffect": ("demon",     None),
    "CardItem.ShowCardInBattle":       ("cardShow",    None),
    "CardItem.ReturnCardInBattle":     ("cardReturn",  None),
    "CardItem.FlipCardFace":           ("cardFlip",    None),
}


def _spine_urls(spine: dict) -> dict:
    """data/extracted/spine/<hash>/x.skel -> /assets/spine/<hash>/x.skel (the server's static mount strips data/extracted)."""
    def url(p):
        p = str(p).replace("\\", "/")
        i = p.find("data/extracted/")
        return "/assets/" + p[i + len("data/extracted/"):] if i >= 0 else p
    return {
        "skel_url": url(spine.get("skel", "")),
        "atlas_url": url(spine.get("atlas", "")),
        "png_urls": [url(p) for p in spine.get("png", [])],
        "atlas_pages": spine.get("atlas_pages", []),
        "stem": spine.get("stem"),
    }


def _char_by_asset_id(assets: dict) -> dict:
    return {c["asset_id"]: c for c in assets["characters"].values() if c.get("asset_id")}


def _actor(char: dict | None, char_id: int, side: str) -> dict:
    if not char:
        return {"charId": char_id, "side": side, "name": str(char_id), "spine": None, "animGroups": {}}
    sp = char.get("spine") or {}
    return {
        "charId": char_id, "side": side,
        "name": char.get("name_en") or char.get("name_cn") or str(char_id),
        "spine": _spine_urls(sp),
        "animGroups": sp.get("skeleton_animation_groups", {}),
    }


_ACTING_KINDS = {"cast", "attack", "death"}


def _attribute_card_sides(turn_list: list) -> None:
    """Fill each card event's side from the OWNER's action (cast/attack/death). show/flip prefer the next acting
    event (forward), return prefers the previous one (backward) — matching the game's ShowCard→act→ReturnCard
    bracket. Mirror of replayModel.js attributeCardSides. See that file for the rationale."""
    carried = None
    for turn in turn_list:
        evs = turn["events"]
        n = len(evs)
        next_acting = [None] * n
        acc = None
        for i in range(n - 1, -1, -1):
            if evs[i]["kind"] in _ACTING_KINDS and evs[i]["side"]:
                acc = evs[i]["side"]
            next_acting[i] = acc
        prev = None
        for i in range(n):
            if evs[i]["kind"] in _ACTING_KINDS and evs[i]["side"]:
                prev = evs[i]["side"]
            if evs[i]["side"] is None and evs[i]["kind"].startswith("card"):
                evs[i]["side"] = (prev or next_acting[i] or carried) if evs[i]["kind"] == "cardReturn" \
                    else (next_acting[i] or prev or carried)
        if prev:
            carried = prev


def assemble_replay(fixture: dict, result: dict, anim: list[dict], assets: dict) -> dict:
    """Pure assembly (testable): fixture + oracle result + parsed ANIM lines -> the Replay object."""
    stat = fixture.get("stat", fixture)
    main = fixture.get("mainViewId") or stat.get("mainViewId")
    by_aid = _char_by_asset_id(assets)

    def pub(side):  # p1/p2 publicData
        return (stat.get(side, {}) or {}).get("publicData", {}) or {}
    p1, p2 = pub("p1"), pub("p2")
    cid1, cid2 = p1.get("characterId"), p2.get("characterId")
    # left = the main-view player (matches the runner's p2IsLeft); fall back to p1=left.
    p2_is_left = main is not None and p2.get("uid") == main and p1.get("uid") != main
    left_cid, right_cid = (cid2, cid1) if p2_is_left else (cid1, cid2)

    left = _actor(by_aid.get(left_cid), left_cid, "L")
    right = _actor(by_aid.get(right_cid), right_cid, "R")

    def side_of(actor_id):
        if actor_id == left_cid: return "L"
        if actor_id == right_cid: return "R"
        return None

    # group ANIM events by turn, in order
    turns: dict[int, list] = {}
    for e in anim:
        kind, group = _EV_MAP.get(e.get("ev", ""), ("other", None))
        turns.setdefault(e.get("turn", 0), []).append({
            "actor": e.get("actor", 0), "side": side_of(e.get("actor", 0)),
            "kind": kind, "group": group,
            "a0": e.get("a0", 0), "a1": e.get("a1", 0), "card": e.get("card", 0),
        })
    turn_list = [{"index": t, "events": turns[t]} for t in sorted(turns)]
    _attribute_card_sides(turn_list)

    # Battle HP starts FULL (hp == maxHp). The fixture publicData lacks the computed battle maxHp (base HP varies
    # per character + buffs), so reconstruct it exactly: startHp = finalHp - Σ(modifyHp deltas in the stream).
    sum_l = sum(ev["a0"] for t in turn_list for ev in t["events"] if ev["kind"] == "modifyHp" and ev["side"] == "L")
    sum_r = sum(ev["a0"] for t in turn_list for ev in t["events"] if ev["kind"] == "modifyHp" and ev["side"] == "R")
    start_hp = {"L": (result.get("leftHp") or 0) - sum_l, "R": (result.get("rightHp") or 0) - sum_r}

    return {
        "left": left, "right": right,
        "turns": turn_list,
        "result": {
            "turns": result.get("turns"), "leftHp": result.get("leftHp"), "rightHp": result.get("rightHp"),
            "hpDelta": result.get("hpDelta"), "expected": result.get("expected"),
            "log": result.get("log", []), "startHp": start_hp,
        },
    }


def run_oracle_with_anim(fixture_path: Path) -> tuple[dict, list[dict]]:
    """Run the oracle on a fixture with animation capture; return (result, anim_events)."""
    env = {**os.environ, "ORACLE_CAPTURE_ANIM": "1"}
    p = subprocess.run(["dotnet", str(ORACLE_DLL), "--run-fixture", str(Path(fixture_path).resolve())],
                       capture_output=True, text=True, env=env, cwd=str(ORACLE_DLL.parent), timeout=120)
    result, anim = {}, []
    for ln in p.stdout.splitlines():
        ln = ln.strip()
        if ln.startswith("ANIM "):
            try: anim.append(json.loads(ln[5:]))
            except Exception: pass
        elif ln.startswith("{") and '"engine"' in ln:
            try: result = json.loads(ln)
            except Exception: pass
    return result, anim


def build_replay_for_fixture(fixture_path: Path) -> dict:
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    assets = json.loads(BATTLE_ASSETS.read_text(encoding="utf-8"))
    result, anim = run_oracle_with_anim(fixture_path)
    return assemble_replay(fixture, result, anim, assets)


# ── FastAPI router (Agent 2 mounts this) ──────────────────────────────────────────────────────────────
try:
    from fastapi import APIRouter, Body
    router = APIRouter()

    @router.post("/api/run-replay")
    def run_replay(payload: dict = Body(...)):
        """Body = the same fixture object /api/run-oracle takes ({p1,p2,battleParams,...} or a full fixture)."""
        import tempfile
        assets = json.loads(BATTLE_ASSETS.read_text(encoding="utf-8"))
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
            json.dump(payload, tf); tmp = tf.name
        try:
            result, anim = run_oracle_with_anim(Path(tmp))
        finally:
            try: os.unlink(tmp)
            except OSError: pass
        return assemble_replay(payload, result, anim, assets)
except ImportError:
    router = None


if __name__ == "__main__":
    fx = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "fixtures" / "dv90m3g-r12.json"
    rep = build_replay_for_fixture(fx)
    print(f"left  = {rep['left']['name']} (char {rep['left']['charId']})  groups={list(rep['left']['animGroups'])[:6]}")
    print(f"right = {rep['right']['name']} (char {rep['right']['charId']})  groups={list(rep['right']['animGroups'])[:6]}")
    print(f"turns = {len(rep['turns'])} | result turns={rep['result']['turns']} hpDelta={rep['result']['hpDelta']}")
    for t in rep["turns"][:4]:
        kinds = [f"{e['side'] or '?'}:{e['kind']}" for e in t["events"]]
        print(f"  turn {t['index']:>2}: {kinds[:10]}")
