#!/usr/bin/env python3
"""
battle_scene_routes.py — prefab-accurate battle SCENE + CAMERA data for the combat replay (ported from the
combat_spike's unity_world_projection). The combat replay was placing characters with guessed screen fractions;
this serves the REAL Unity orthographic camera projection + character world positions + the scene background so the
viewer matches the game prefab.

Mounted into fixture_editor_server.py via the same loop that mounts models_router / prep_router.

Endpoints:
  GET /api/game/battle-scene            -> { design, camera, bases:{left,right}, actors:{left,right}, background }
  GET /assets/battle-backgrounds/<name> -> the scene preview PNG (served here so we don't need an app.mount)

camera = the Cinemachine orthographic projection (orthographicSize, visibleWidth/Height, unitPx, center). actors =
each character's world base projected to DESIGN px via Camera.WorldToScreenPoint. The client maps design→host with
its existing makeFit and scales each Spine by unitPx so the characters are the right SIZE for the camera.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import sys
sys.path.insert(0, str(ROOT / "scripts"))   # unity_world_projection lives next to the server
from unity_world_projection import battle_camera, world_to_screen, project_battle_sides  # noqa: E402
from unity_ui_projection import compile_ui_projection, direct_child_paths  # noqa: E402

SCENE = "BattleScene_1_2"
SCENE_MANIFEST = ROOT / "data" / "extracted" / "battle_scene_sprites" / SCENE / "manifest.json"
MARKER_MANIFEST = ROOT / "data" / "extracted" / "battle_character_markers" / "manifest.json"
BATTLE_LAYOUT_MANIFEST = ROOT / "data" / "game" / "battle_layout_manifest.json"
BG_DIR = ROOT / "data" / "extracted" / "battle_backgrounds"
AVATAR_DIR = ROOT / "data" / "wiki" / "characters" / "avatars"
PREVIEW = f"BattleScenePreview_{SCENE.replace('BattleScene_', '')}.png"
DESIGN_W, DESIGN_H = 2048.0, 1152.0

_marker_cache = None
_ui_layout_cache = None


def _markers_for(asset_id) -> dict:
    """Per-character marker prefab (SkeletonAnimation scale, HpBarPoint, FloatTextPoint, AttackFxPoint, ...)."""
    global _marker_cache
    if asset_id is None:
        return {}
    if _marker_cache is None:
        _marker_cache = (json.loads(MARKER_MANIFEST.read_text(encoding="utf-8")).get("prefabs") if MARKER_MANIFEST.exists() else {}) or {}
    for skin in (0, 1):
        key = f"Character_Battle_{asset_id}_{skin}"
        if key in _marker_cache:
            return _marker_cache[key]
    return {}


def _ui_layout() -> dict:
    """Prefab UI layout (character-independent) for the DOM overlays: design + statusBar(+parts) + playerInfo +
    deck CardSlots + activeCard/cardStart. Ported from combat_spike's _combat_layout_payload UI portion. The DOM
    overlays in BattleReplay position against these via layoutStyle (percentage of design) so they scale at any size."""
    global _ui_layout_cache
    if _ui_layout_cache is not None:
        return _ui_layout_cache
    manifest = json.loads(BATTLE_LAYOUT_MANIFEST.read_text(encoding="utf-8"))
    battle_root = manifest["roots_by_name"]["BattleLayer"][0]["hierarchy"]
    projected = compile_ui_projection(battle_root, DESIGN_W, DESIGN_H)
    nodes_by_path = projected["nodesByPath"]

    def require(path: str) -> dict:
        node = nodes_by_path.get(path)
        if not node:
            raise RuntimeError(f"Projected battle layout path not found: {path}")
        return node

    def deck_cards(side: str) -> list[dict]:
        cards = []
        container_path = f"BattleLayer/{side.capitalize()}CharacterUI/CardContainer"
        for index, path in enumerate(direct_child_paths(battle_root, container_path, "CardSlot")):
            slot = require(path)
            cards.append({"slot": index, "path": path, **slot["rect"], "runtime": slot["runtime"]})
        return cards

    status_bar_parts = {}
    for side, root_path in {
        "left": "BattleLayer/LeftCharacterUI/StatusBar",
        "right": "BattleLayer/RightCharacterUI/StatusBar",
    }.items():
        root_rect = require(root_path)["rect"]

        def relative(path: str, _root=root_rect) -> dict:
            rect = require(path)["rect"]
            return {
                "path": path,
                "left": rect["left"] - _root["left"],
                "top": rect["top"] - _root["top"],
                "width": rect["width"],
                "height": rect["height"],
                "runtime": {**rect.get("runtime", {}),
                            "offsetX": rect["left"] - _root["left"], "offsetY": -(rect["top"] - _root["top"]),
                            "anchorX": 0, "anchorY": 1},
            }

        status_bar_parts[side] = {
            "mainBuffDisplay": relative(f"{root_path}/MainBuffDisplay"),
            "animaItem": relative(f"{root_path}/MainBuffDisplay/AnimaItem"),      # Qi/灵气 icon (灵气图标)
            "animaLabel": relative(f"{root_path}/MainBuffDisplay/AnimaItem/Label"),
            "hpSlider": relative(f"{root_path}/HpSlider"),
            "hpBackground": relative(f"{root_path}/HpSlider/Background"),          # HP track sprite (Background)
            "hpFillArea": relative(f"{root_path}/HpSlider/Fill Area"),
            "hpFill": relative(f"{root_path}/HpSlider/Fill Area/Fill"),            # the moving HP fill (血条白)
            "hpReduce": relative(f"{root_path}/HpSlider/Fill Area/Reduce"),        # red damage trail
            "hpAdd": relative(f"{root_path}/HpSlider/Fill Area/Add"),              # green heal trail
            "hpCalibrations": relative(f"{root_path}/HpSlider/Fill Area/Calibrations"),  # tick marks (1 per 20 HP)
            "hpLabel": relative(f"{root_path}/HpLabel"),
            "defItem": relative(f"{root_path}/DefItem"),                           # DEF icon (Icon_盾)
            "defLabel": relative(f"{root_path}/DefItem/Label"),
        }

    player_info = {}
    for side, root_path in {
        "left": "BattleLayer/LeftCharacterUI/PlayerInfo",
        "right": "BattleLayer/RightCharacterUI/PlayerInfo",
    }.items():
        def opt(path: str):   # some PlayerInfo nodes (Tipo/Exp) exist but may not project; tolerate absence
            node = nodes_by_path.get(path)
            return node["rect"] if node else None

        player_info[side] = {
            "root": require(root_path)["rect"],
            "avatar": require(f"{root_path}/Avatar")["rect"],
            "avatarPortrait": opt(f"{root_path}/Avatar/Mask/Avata"),   # the masked character portrait
            "avatarFrame": opt(f"{root_path}/Avatar/Image"),           # frame ring (ContentBar_头像框)
            "name": require(f"{root_path}/NameLabel")["rect"],
            "life": require(f"{root_path}/LifeBottom")["rect"],
            "lifeLabel": require(f"{root_path}/LifeBottom/LifeLabel")["rect"],
            "exp": opt(f"{root_path}/Exp"),                            # 修为 (cultivation/exp)
            "expLabel": opt(f"{root_path}/Exp/Exp/ExpLabel"),
            "tipo": opt(f"{root_path}/Tipo"),                          # 体魄 physique (DX-only, hidden when 0)
            "tipoLabel": opt(f"{root_path}/Tipo/Tipo/TipoLabel"),
            "talentDisplay": require(f"{root_path}/Avatar/TalentDisplay")["rect"],
        }

    _ui_layout_cache = {
        "design": {"width": DESIGN_W, "height": DESIGN_H},
        "statusBar": {
            "left": require("BattleLayer/LeftCharacterUI/StatusBar")["rect"],
            "right": require("BattleLayer/RightCharacterUI/StatusBar")["rect"],
        },
        "statusBarParts": status_bar_parts,
        "playerInfo": player_info,
        "activeCard": {
            "left": require("BattleLayer/LeftCharacterUI/CardMoveTarget")["rect"],
            "right": require("BattleLayer/RightCharacterUI/CardMoveTarget")["rect"],
        },
        "cardStart": {
            "left": require("BattleLayer/LeftCharacterUI/CardStartPos")["rect"],
            "right": require("BattleLayer/RightCharacterUI/CardStartPos")["rect"],
        },
        "deck": {"left": {"cards": deck_cards("left")}, "right": {"cards": deck_cards("right")}},
        # the REAL extracted game sprites for the status bar (so the HP bar etc. is pixel-exact, not a CSS gradient)
        "sprites": {k: f"/assets/battle-statusbar/{k}" for k in STATUSBAR_SPRITES},
    }
    return _ui_layout_cache


# logical key -> extracted sprite filename (Chinese names served via ascii keys to avoid URL-encoding issues)
STATUSBAR_SPRITES = {
    "hpFill": "血条白.png",          # the moving HP fill bar
    "hpTrack": "Background.png",      # HP slider track / frame
    "tick": "Circle.png",            # calibration tick (1 per 20 HP)
    "def": "Icon_盾.png",            # DEF icon
    "qi": "灵气图标.png",            # Qi / anima icon
    "avatarFrame": "ContentBar_头像框.png",   # avatar ring frame
}
STATUSBAR_DIR = ROOT / "data" / "extracted" / "battle_statusbar_sprites"


def battle_scene_payload(left_id=None, right_id=None) -> dict:
    scene_manifest = json.loads(SCENE_MANIFEST.read_text(encoding="utf-8")) if SCENE_MANIFEST.exists() else {"camera": {}}
    cam_cfg = scene_manifest.get("camera") or {}
    proj = project_battle_sides(scene_manifest, {"left": _markers_for(left_id), "right": _markers_for(right_id)},
                                width=DESIGN_W, height=DESIGN_H)
    cam = proj["camera"]
    # actors fall back to the bare camera-projected base if a character has no marker prefab
    fb = battle_camera(cam_cfg, width=DESIGN_W, height=DESIGN_H)
    base = proj["bases"]
    return {
        "design": {"width": DESIGN_W, "height": DESIGN_H},
        "camera": cam,
        "bases": base,
        # per-side: actor (feet, design px), skeletonScale {x,y}, hp/floatText/hit/attackFx markers (design px)
        "left": proj["players"]["left"] or {"actor": world_to_screen(fb, base["left"])},
        "right": proj["players"]["right"] or {"actor": world_to_screen(fb, base["right"])},
        "background": f"/assets/battle-backgrounds/{PREVIEW}" if (BG_DIR / PREVIEW).exists() else None,
        "scene": SCENE,
        # prefab UI layout (character-independent) for the scaling DOM overlays (HP bars, buffs, deck, hud)
        "layout": _ui_layout(),
    }


try:
    from fastapi import APIRouter
    from fastapi.responses import FileResponse, JSONResponse
    router = APIRouter()

    @router.get("/api/game/battle-scene")
    def api_battle_scene(left: int | None = None, right: int | None = None):
        return battle_scene_payload(left, right)

    @router.get("/api/game/combat-layout")
    def api_combat_layout():
        return _ui_layout()

    @router.get("/assets/battle-backgrounds/{name}")
    def api_battle_background(name: str):
        # guard against traversal; only serve png files from the backgrounds dir
        safe = Path(name).name
        p = BG_DIR / safe
        if p.suffix.lower() == ".png" and p.exists():
            return FileResponse(str(p), media_type="image/png")
        return JSONResponse(status_code=404, content={"error": f"no background {safe}"})

    @router.get("/assets/battle-statusbar/{key}")
    def api_statusbar_sprite(key: str):
        fname = STATUSBAR_SPRITES.get(key)
        p = STATUSBAR_DIR / fname if fname else None
        if p and p.exists():
            return FileResponse(str(p), media_type="image/png")
        return JSONResponse(status_code=404, content={"error": f"no statusbar sprite {key}"})

    @router.get("/assets/character-avatars/{name}")
    def api_character_avatar(name: str):
        # character portrait for the battle HUD (data/wiki/characters/avatars/<charId>-avatar.png)
        safe = Path(name).name
        p = AVATAR_DIR / safe
        if p.suffix.lower() == ".png" and p.exists():
            return FileResponse(str(p), media_type="image/png")
        return JSONResponse(status_code=404, content={"error": f"no avatar {safe}"})
except ImportError:
    router = None


if __name__ == "__main__":
    import pprint
    pprint.pp(battle_scene_payload())
