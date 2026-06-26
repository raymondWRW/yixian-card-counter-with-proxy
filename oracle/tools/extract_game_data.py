#!/usr/bin/env python3
"""Extract the Oracle's game inputs from the installed game's Unity Addressables bundles.

Writes:
  oracle/data/extracted/DarkSun.HotUpdate.dll   (the hot-update gameplay assembly the Oracle JIT-loads)
  oracle/data/extracted/configs/<Name>.dat      (every protobuf config TextAsset the game's ConfigLoader reads)

Robust to game updates: it SCANS every bundle for the TextAssets by name (bundle hashes change each patch),
so re-run this after the game updates, then re-run oracle/build.sh.

Usage:  python oracle/tools/extract_game_data.py [path-to-YiXianPai-install]
"""
import os, sys, re, UnityPy

DEFAULT_GAME = r"C:\Program Files (x86)\Steam\steamapps\common\YiXianPai"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "data", "extracted"))
CFG = os.path.join(OUT, "configs")


def unity_version(game_dir: str) -> str:
    ggm = os.path.join(game_dir, "YiXianPai_Data", "globalgamemanagers")
    m = re.search(rb"(\d+\.\d+\.\d+[a-z]\d+)", open(ggm, "rb").read(400))
    return m.group(1).decode() if m else "2020.3.49f1"


def raw_bytes(ta) -> bytes:
    s = ta.m_Script
    return bytes(s) if isinstance(s, (bytes, bytearray)) else s.encode("utf-8", "surrogateescape")


def main():
    game = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GAME
    aa = os.path.join(game, "YiXianPai_Data", "StreamingAssets", "aa", "StandaloneWindows64")
    if not os.path.isdir(aa):
        sys.exit(f"Addressables dir not found: {aa}")
    UnityPy.config.FALLBACK_UNITY_VERSION = unity_version(game)
    os.makedirs(CFG, exist_ok=True)
    dll = pdb = configs = 0
    for fn in os.listdir(aa):
        if not fn.endswith(".bundle"):
            continue
        try:
            env = UnityPy.load(os.path.join(aa, fn))
        except Exception:
            continue
        for obj in env.objects:
            if obj.type.name != "TextAsset":
                continue
            try:
                ta = obj.read(); name = ta.m_Name or ""
            except Exception:
                continue
            if name == "DarkSun.HotUpdate":
                open(os.path.join(OUT, "DarkSun.HotUpdate.dll"), "wb").write(raw_bytes(ta)); dll += 1
            elif name == "DarkSun.HotUpdate.pdb":
                open(os.path.join(OUT, "DarkSun.HotUpdate.pdb"), "wb").write(raw_bytes(ta)); pdb += 1
            elif name.endswith("Config"):
                open(os.path.join(CFG, name + ".dat"), "wb").write(raw_bytes(ta)); configs += 1
    print(f"Unity {UnityPy.config.FALLBACK_UNITY_VERSION}: DLL={dll} PDB={pdb} configs={configs} -> {OUT}")
    if not dll or not configs:
        sys.exit("ERROR: missing DLL or configs — game layout may have changed")


if __name__ == "__main__":
    main()
