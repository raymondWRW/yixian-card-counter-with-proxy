# -*- coding: utf-8 -*-
"""oracle_bootstrap.py — keep the Yi Xian Oracle's game data current with the
installed game, so the damage/review engine never lags a patch.

On startup we compare the installed game's version key to what the Oracle was
last synced against. If the game updated (or this is a first run), we:

  1. extract DarkSun.HotUpdate.dll + configs from the user's own game install
     (no game code is bundled/redistributed — each user extracts from their copy),
  2. if GameAssembly.dll (the IL2CPP core) changed, re-dump DummyDll with the
     bundled Il2CppDumper and regenerate the facades (self-healing),
  3. otherwise reuse the bundled facades.

Layout (ORACLE_HOME = writable):
  <home>/data/extracted/{DarkSun.HotUpdate.dll, configs/*.dat}
  <home>/UnityStubs/bin/facades/           (hand facades — from bundle/repo)
  <home>/UnityStubs/bin/facades-gen/       (generated; + .gakey of its GameAssembly)
  <home>/tools/Il2CppDumper/v6.7.46/DummyDll/
  <home>/auto_patch.json
  <home>/.oracle_version                   (last-synced game key)

Dev: ORACLE_HOME = repo/oracle (already populated); bundle = repo/oracle.
Frozen exe: ORACLE_HOME = %LOCALAPPDATA%/YiXianCounter/oracle; bundle = _MEIPASS/oracle.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

_BASE = Path(__file__).resolve().parent          # proxy/
_REPO = _BASE.parent


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "YiXianCounter"


def _exe_resources() -> Path:
    """Small resources bundled inside the exe (engine.json). _MEIPASS when frozen."""
    if _frozen():
        return Path(getattr(sys, "_MEIPASS", str(_REPO))) / "oracle"
    return _REPO / "oracle"


def _engine_dir() -> Path:
    """The Oracle engine root: a separately-downloaded bundle when frozen (the exe is
    kept small to fit a 100MB release limit), or the repo's built oracle/ in dev. Holds
    Oracle.exe + facades + Il2CppDumper + auto_patch, and (writable) the extracted game
    data + regenerated facades-gen. Serves as BOTH the read-only source and ORACLE_HOME."""
    if _frozen():
        return _appdata() / "engine"
    return _REPO / "oracle"


# _bundle and _home are now the same dir (the engine dir) — kept as names for clarity.
def _bundle() -> Path:
    return _engine_dir()


def _home() -> Path:
    return _engine_dir()


def oracle_exe() -> Path:
    if _frozen():
        return _engine_dir() / "Oracle" / "Oracle.exe"
    return _REPO / "oracle" / "Oracle" / "bin" / "Release" / "net8.0" / "Oracle.exe"


def ensure_engine() -> str:
    """Frozen only: download + extract the Oracle engine bundle (self-contained Oracle.exe
    + facades + Il2CppDumper) on first run / when the bundled engine.json version changes.
    Reads engine.json (bundled in the exe) for {version, url, sha256}. No-op in dev.
    Returns a status string; the engine is unusable until this succeeds."""
    if not _frozen():
        return "dev"
    import json
    try:
        meta = json.loads((_exe_resources() / "engine.json").read_text(encoding="utf-8"))
    except Exception as e:
        _log(f"engine.json missing/unreadable: {e}")
        return "no engine manifest"
    edir = _engine_dir()
    marker = edir / ".engine_version"
    if (edir / "Oracle" / "Oracle.exe").exists() and marker.exists():
        try:
            if marker.read_text(encoding="utf-8").strip() == str(meta.get("version", "")):
                return "engine present"
        except Exception:
            pass
    url, sha = meta.get("url", ""), meta.get("sha256", "")
    if not url:
        return "no engine url"
    _log(f"downloading Oracle engine v{meta.get('version')} ({url}) …")
    import urllib.request, hashlib, zipfile, tempfile
    edir.mkdir(parents=True, exist_ok=True)
    zpath = Path(tempfile.gettempdir()) / "yx_oracle_engine.zip"
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as e:
        _log(f"engine download failed: {e}")
        return "engine download failed"
    if sha:
        h = hashlib.sha256()
        with open(zpath, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        if h.hexdigest() != sha:
            _log("engine sha256 mismatch — discarding")
            try: zpath.unlink()
            except Exception: pass
            return "engine checksum mismatch"
    # Fresh extract (clear stale Oracle/facades, keep extracted game data if present).
    for sub in ("Oracle", "UnityStubs", "tools"):
        shutil.rmtree(edir / sub, ignore_errors=True)
    try:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(edir)
    except Exception as e:
        _log(f"engine extract failed: {e}")
        return "engine extract failed"
    try:
        marker.write_text(str(meta.get("version", "")), encoding="utf-8")
        zpath.unlink()
    except Exception:
        pass
    _log(f"engine ready ({meta.get('version')})")
    return "engine downloaded"


def _game_dir(explicit: str = None) -> Path | None:
    """Locate the installed game directory (contains GameAssembly.dll)."""
    cands = []
    if explicit:
        cands.append(explicit)
    if os.environ.get("YX_GAME_EXE"):
        cands.append(os.environ["YX_GAME_EXE"])
    try:
        import json
        cfg = _REPO / "native_hud" / "bridge" / "YiXianHUD_config.json"
        if cfg.exists():
            ge = json.loads(cfg.read_text(encoding="utf-8")).get("game_exe")
            if ge:
                cands.append(ge)
    except Exception:
        pass
    cands.append(r"C:\Program Files (x86)\Steam\steamapps\common\YiXianPai\YiXianPai.exe")
    for c in cands:
        p = Path(c)
        d = p.parent if p.suffix.lower() == ".exe" else p
        if (d / "GameAssembly.dll").exists():
            return d
    return None


def _ga_path(game_dir: Path) -> Path:
    return game_dir / "GameAssembly.dll"


def _meta_path(game_dir: Path) -> Path:
    return game_dir / "YiXianPai_Data" / "il2cpp_data" / "Metadata" / "global-metadata.dat"


def _ver_key(game_dir: Path) -> str:
    """Cheap version key: GameAssembly + metadata size/mtime. Avoids hashing 70MB each launch."""
    parts = []
    for p in (_ga_path(game_dir), _meta_path(game_dir)):
        try:
            st = p.stat()
            parts.append(f"{p.name}:{st.st_size}:{int(st.st_mtime)}")
        except Exception:
            parts.append(f"{p.name}:0")
    return "|".join(parts)


def _ga_key(game_dir: Path) -> str:
    """Facades basis key — must be STABLE across machines for the same game version
    (so a user can reuse the bundled facades). Uses file SIZES only (mtime varies by
    download); same IL2CPP build → same sizes."""
    try:
        ga = _ga_path(game_dir).stat().st_size
        md = _meta_path(game_dir).stat().st_size
        return f"{ga}:{md}"
    except Exception:
        return "0"


# ── game-data extraction (UnityPy; bundled) ───────────────────────────────────
def _unity_version(game_dir: Path) -> str:
    import re
    try:
        b = (game_dir / "YiXianPai_Data" / "globalgamemanagers").read_bytes()[:400]
        m = re.search(rb"(\d+\.\d+\.\d+[a-z]\d+)", b)
        if m:
            return m.group(1).decode()
    except Exception:
        pass
    return "2020.3.49f1"


def _extract(game_dir: Path, out_dir: Path) -> tuple[int, int]:
    """Extract DarkSun.HotUpdate.dll + every *Config TextAsset into out_dir. Scans by name
    (robust to Addressables bundle-hash renames each patch). Returns (dll_count, config_count)."""
    import UnityPy
    UnityPy.config.FALLBACK_UNITY_VERSION = _unity_version(game_dir)
    aa = game_dir / "YiXianPai_Data" / "StreamingAssets" / "aa" / "StandaloneWindows64"
    cfg_dir = out_dir / "configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    def raw(ta):
        s = ta.m_Script
        return bytes(s) if isinstance(s, (bytes, bytearray)) else s.encode("utf-8", "surrogateescape")

    dll = cfgs = 0
    for fn in os.listdir(aa):
        if not fn.endswith(".bundle"):
            continue
        try:
            env = UnityPy.load(str(aa / fn))
        except Exception:
            continue
        for obj in env.objects:
            if obj.type.name != "TextAsset":
                continue
            try:
                ta = obj.read()
                name = ta.m_Name or ""
            except Exception:
                continue
            if name == "DarkSun.HotUpdate":
                (out_dir / "DarkSun.HotUpdate.dll").write_bytes(raw(ta)); dll += 1
            elif name == "DarkSun.HotUpdate.pdb":
                (out_dir / "DarkSun.HotUpdate.pdb").write_bytes(raw(ta))
            elif name.endswith("Config"):
                (cfg_dir / (name + ".dat")).write_bytes(raw(ta)); cfgs += 1
    return dll, cfgs


def _il2cppdump(game_dir: Path, dummy_out: Path) -> bool:
    """Run the bundled Il2CppDumper → DummyDll into dummy_out's parent. Returns True on success."""
    exe = _bundle() / "tools" / "Il2CppDumper" / "v6.7.46" / "Il2CppDumper.exe"
    if not exe.exists():
        return False
    out_parent = dummy_out.parent
    out_parent.mkdir(parents=True, exist_ok=True)
    try:
        # Il2CppDumper exits with a "press any key" error under no console — harmless; check output.
        subprocess.run([str(exe), str(_ga_path(game_dir)), str(_meta_path(game_dir)), str(out_parent)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=300, cwd=str(out_parent))
    except Exception:
        pass
    return dummy_out.exists() and any(dummy_out.glob("*.dll"))


def _gen_facades(home: Path) -> bool:
    """Run Oracle.exe --gen-facades (reads home/tools/.../DummyDll → home/UnityStubs/bin/facades-gen)."""
    exe = oracle_exe()
    if not exe.exists():
        return False
    env = dict(os.environ); env["ORACLE_HOME"] = str(home)
    try:
        subprocess.run([str(exe), "--gen-facades"], env=env, timeout=600,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(exe.parent))
    except Exception:
        pass
    gen = home / "UnityStubs" / "bin" / "facades-gen"
    return gen.exists() and any(gen.glob("*.dll"))


def _logfile() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "YiXianCounter"
    return base / "oracle-sync.log"


def _log(msg: str):
    print(f"[oracle-sync] {msg}", flush=True)
    # Also to a file — the packaged exe is --windowed, so stdout goes nowhere.
    try:
        lf = _logfile()
        lf.parent.mkdir(parents=True, exist_ok=True)
        with lf.open("a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


def ensure_current(game_dir: str = None) -> str:
    """Make the Oracle's data current with the installed game. Returns a status string.
    Sets os.environ ORACLE_HOME + ORACLE_EXE so oracle_sim/the worker use the right paths.
    Safe to call on a background thread; can take ~30-120s on a first run / after a game patch."""
    # 0. Make sure the engine bundle is present (frozen: download on first run).
    est = ensure_engine()
    if _frozen() and est not in ("engine present", "engine downloaded"):
        _log(f"engine not ready: {est}")
        return est

    home = _home()
    bundle = _bundle()
    os.environ["ORACLE_EXE"] = str(oracle_exe())
    os.environ["ORACLE_HOME"] = str(home)
    _log(f"ensure_current: frozen={_frozen()} home={home} exe_exists={oracle_exe().exists()}")

    gdir = _game_dir(game_dir)
    if gdir is None:
        _log("game install not found")
        return "game install not found — Oracle unavailable"
    _log(f"game dir: {gdir}")

    ver = _ver_key(gdir)
    marker = home / ".oracle_version"
    extracted_dll = home / "data" / "extracted" / "DarkSun.HotUpdate.dll"
    if marker.exists() and extracted_dll.exists():
        try:
            if marker.read_text(encoding="utf-8").strip() == ver:
                return "already current"
        except Exception:
            pass

    _log(f"syncing Oracle to installed game ({'first run' if not marker.exists() else 'game updated'})…")
    home.mkdir(parents=True, exist_ok=True)
    # (facades / auto_patch already live in the engine dir, which IS home — no scaffolding.)

    # Extract game data.
    out = home / "data" / "extracted"
    try:
        dll, cfgs = _extract(gdir, out)
        _log(f"extracted DLL={dll} configs={cfgs}")
    except Exception:
        import traceback
        _log("extraction EXCEPTION:\n" + traceback.format_exc())
        return "extraction failed"
    if dll == 0 or cfgs == 0 or not (out / "DarkSun.HotUpdate.dll").exists():
        _log("extraction produced no DLL/configs — not marking current (will retry)")
        return "extraction incomplete"

    # 3. Facades: reuse if their GameAssembly matches; else regen (re-dump + --gen-facades).
    # Facades-gen ships inside the engine (stamped with the GameAssembly it was built against).
    # Reuse it if the installed game's GameAssembly matches; otherwise self-heal: re-dump with
    # Il2CppDumper and regenerate.
    gen = home / "UnityStubs" / "bin" / "facades-gen"
    gakey_file = gen / ".gakey"
    cur_gakey = _ga_key(gdir)
    have_gen = gen.exists() and any(gen.glob("*.dll")) and \
        (gakey_file.exists() and gakey_file.read_text(encoding="utf-8").strip() == cur_gakey)

    if have_gen:
        _log("facades: engine set matches installed GameAssembly")
    else:
        _log("facades: GameAssembly differs from engine — re-dumping + regenerating (self-heal)…")
        dummy = home / "tools" / "Il2CppDumper" / "v6.7.46" / "DummyDll"
        if _il2cppdump(gdir, dummy) and _gen_facades(home):
            gen.mkdir(parents=True, exist_ok=True)
            try:
                (gen / ".gakey").write_text(cur_gakey, encoding="utf-8")
            except Exception:
                pass
            _log("facades regenerated")
        else:
            _log("facade regen FAILED — engine may not load")
            return "facade regen failed"

    try:
        marker.write_text(ver, encoding="utf-8")
    except Exception:
        pass
    return "synced"
