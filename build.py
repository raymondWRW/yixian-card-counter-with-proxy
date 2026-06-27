"""
Build YiXianCounter.exe (the MAIN app) via PyInstaller.

Run from the repo root:
  .venv\Scripts\python.exe build.py

Prints a paste-ready dist_share/version.json snippet at the end (with the
exe's SHA256) so the release flow is bump-version → build → paste.
"""
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The final SHA banner uses box-drawing chars; force utf-8 stdout so it doesn't
# crash on a cp1252 console (the build itself succeeds either way).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
SEP = ";" if sys.platform.startswith("win") else ":"

# Clean previous build artifacts
for d in ("build", "dist", "__pycache__"):
    p = HERE / d
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
spec = HERE / "YiXianCounter.spec"
if spec.exists():
    spec.unlink()

icon_arg = []
for cand in ("icon.ico", "native_hud/icon.ico"):
    if (HERE / cand).exists():
        icon_arg = ["--icon", cand]
        break

# ── Yi Xian Oracle engine (the ONLY damage/review engine — no yisim/node) ────────────────────
# The heavy engine (self-contained Oracle.exe + .NET runtime + facades + Il2CppDumper, ~100MB /
# ~42MB zipped) does NOT fit a 100MB release limit alongside the app, so it is shipped as a
# SEPARATE dist_share/oracle-engine-v{VER}.zip. oracle_bootstrap downloads + sha-verifies +
# extracts it on first run (from the url in the bundled engine.json). The exe stays ~30MB.
# The game DLL/configs are never bundled — extracted from the user's own install at runtime.
import json as _json
try:
    sys.path.insert(0, str(HERE)); from version import VERSION
except Exception:
    VERSION = "0.0.0"
GITEE = "https://gitee.com/hiddensquid12321/yixian-card-counter-with-proxy/releases/download"

ORACLE = HERE / "oracle"
PUB = HERE / "_oracle_pub"
shutil.rmtree(PUB, ignore_errors=True)
print("Publishing self-contained Oracle.exe …", flush=True)
pub = subprocess.run(
    ["dotnet", "publish", str(ORACLE / "Oracle" / "Oracle.csproj"), "-c", "Release",
     "-r", "win-x64", "--self-contained", "true", "-o", str(PUB)],
    cwd=str(HERE))
if pub.returncode != 0 or not (PUB / "Oracle.exe").exists():
    sys.exit("Oracle publish failed")

# Stamp facades-gen with the builder's GameAssembly key, so a user on the SAME game version
# reuses these facades; a different version triggers a self-heal regen (Il2CppDumper) at runtime.
def _ga_key():
    game = r"C:\Program Files (x86)\Steam\steamapps\common\YiXianPai"
    try:
        ga = (Path(game) / "GameAssembly.dll").stat().st_size
        md = (Path(game) / "YiXianPai_Data" / "il2cpp_data" / "Metadata" / "global-metadata.dat").stat().st_size
        return f"{ga}:{md}"
    except Exception:
        return ""
gen = ORACLE / "UnityStubs" / "bin" / "facades-gen"
if gen.exists() and _ga_key():
    (gen / ".gakey").write_text(_ga_key(), encoding="utf-8")

# Stage the engine bundle (Oracle + facades + Il2CppDumper + auto_patch) and zip it into dist_share.
ESTAGE = HERE / "_engine_stage"
shutil.rmtree(ESTAGE, ignore_errors=True)
shutil.copytree(PUB, ESTAGE / "Oracle")
shutil.copytree(ORACLE / "UnityStubs" / "bin" / "facades", ESTAGE / "UnityStubs" / "bin" / "facades")
shutil.copytree(ORACLE / "UnityStubs" / "bin" / "facades-gen", ESTAGE / "UnityStubs" / "bin" / "facades-gen")
shutil.copytree(ORACLE / "tools" / "Il2CppDumper" / "v6.7.46", ESTAGE / "tools" / "Il2CppDumper" / "v6.7.46",
                ignore=shutil.ignore_patterns("DummyDll"))
shutil.copy2(ORACLE / "auto_patch.json", ESTAGE / "auto_patch.json")

share = HERE / "dist_share"
share.mkdir(exist_ok=True)
engine_zip = share / f"oracle-engine-v{VERSION}.zip"
if engine_zip.exists():
    engine_zip.unlink()
print("Zipping engine bundle …", flush=True)
shutil.make_archive(str(engine_zip)[:-4], "zip", str(ESTAGE))
_eh = hashlib.sha256()
with engine_zip.open("rb") as f:
    for chunk in iter(lambda: f.read(65536), b""):
        _eh.update(chunk)
engine_sha = _eh.hexdigest()
engine_url = f"{GITEE}/main-v{VERSION}/oracle-engine-v{VERSION}.zip"
# engine.json — the only Oracle artifact bundled in the exe; the bootstrap reads url+sha here.
(ORACLE / "engine.json").write_text(
    _json.dumps({"version": VERSION, "url": engine_url, "sha256": engine_sha}, indent=2), encoding="utf-8")
print(f"  engine: {engine_zip.name}  {round(engine_zip.stat().st_size/1048576,1)}MB  sha={engine_sha[:12]}")

# Only the tiny engine.json + oracle_pool.py go into the exe; the engine itself is downloaded.
oracle_args = []
for src, dst in [("oracle/engine.json", "oracle"),
                 ("oracle/scripts/oracle_pool.py", "oracle/scripts")]:
    oracle_args += ["--add-data", f"{src}{SEP}{dst}"]

# Build OUTSIDE the OneDrive-synced repo: OneDrive locks/moves files in build/ mid-run, which makes
# PyInstaller's base_library.zip vanish (FileNotFoundError). Point work/dist/spec at a temp dir.
BUILD_TMP = Path(tempfile.gettempdir()) / "yxbuild"
shutil.rmtree(BUILD_TMP, ignore_errors=True)
BUILD_TMP.mkdir(parents=True, exist_ok=True)

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name", "YiXianCounter",
    "--workpath", str(BUILD_TMP / "build"),
    "--distpath", str(BUILD_TMP / "dist"),
    # NOTE: spec stays in HERE — PyInstaller resolves relative --add-data paths against the spec dir,
    # so moving it to TEMP breaks them. Only work/dist (where base_library.zip lives) need to leave OneDrive.
    *icon_arg,
    *oracle_args,
    # The main app's web/ folder + the shared proxy/ + tools (card maps, derivation data).
    "--add-data", f"web{SEP}web",
    "--add-data", f"proxy{SEP}proxy",
    "--add-data", f"tools{SEP}tools",
    # frida capture agent (loaded by runtime.start_frida_capture).
    "--add-data", f"native_hud/_build/capture.agent.js{SEP}native_hud/_build",
    "--collect-all", "frida",
    "--collect-all", "blackboxprotobuf",
    "--collect-all", "webview",
    "--collect-all", "UnityPy",          # oracle_bootstrap extracts game data with UnityPy
    "--collect-all", "msgpack",
    "--hidden-import", "addon",
    "--hidden-import", "shadow_state",
    "--hidden-import", "game_state",
    "--hidden-import", "state_queue",
    "--hidden-import", "card_names",
    "--hidden-import", "battle_log",
    "--hidden-import", "decoder",
    "--hidden-import", "msgpack",
    "--hidden-import", "updater",
    "--hidden-import", "version",
    "--hidden-import", "lingyu_merge",
    "--hidden-import", "proxy_view",
    "--hidden-import", "runtime",
    "--hidden-import", "frida",
    "--hidden-import", "oracle_bootstrap",
    "--hidden-import", "oracle_sim",
    "--hidden-import", "recent_battles",
    "--hidden-import", "game_archive",
    "app.py",
]
print("Running:", " ".join(cmd))
result = subprocess.run(cmd, cwd=str(HERE))
if result.returncode != 0:
    sys.exit(result.returncode)

built_exe = BUILD_TMP / "dist" / "YiXianCounter.exe"
target_exe = HERE / "YiXianCounter.exe"
if built_exe.exists():
    if target_exe.exists():
        target_exe.unlink()
    shutil.move(str(built_exe), str(target_exe))
for d in ("build", "dist", "_oracle_pub", "_engine_stage"):
    shutil.rmtree(HERE / d, ignore_errors=True)
shutil.rmtree(BUILD_TMP, ignore_errors=True)
if spec.exists():
    spec.unlink()

share = HERE / "dist_share"
share.mkdir(exist_ok=True)
shutil.copy2(str(target_exe), str(share / "YiXianCounter.exe"))

# Compute SHA256 so the release manifest stays consistent with the binary.
h = hashlib.sha256()
with target_exe.open("rb") as f:
    for chunk in iter(lambda: f.read(65536), b""):
        h.update(chunk)
sha256 = h.hexdigest()

try:
    sys.path.insert(0, str(HERE))
    from version import VERSION
except Exception:
    VERSION = "?"

print(f"\nBuilt: {target_exe}  ({round(target_exe.stat().st_size/1048576,1)}MB)")
print(f"Engine: {engine_zip}  ({round(engine_zip.stat().st_size/1048576,1)}MB)")
print(f"Share folder ready: {share}")
print(f"\n── Release main-v{VERSION} — attach BOTH files (each < 100MB) ──")
print(f"  exe sha256:    {sha256}")
print(f"  engine sha256: {engine_sha}")
print("\nPaste this into dist_share/version.json:")
print(
    "{\n"
    f'  "version": "{VERSION}",\n'
    f'  "url": "{GITEE}/main-v{VERSION}/YiXianCounter.exe",\n'
    f'  "sha256": "{sha256}",\n'
    '  "notes": "What changed in this release."\n'
    "}"
)
print(f"\nCreate Gitee Release 'main-v{VERSION}' and attach BOTH:")
print(f"  - {target_exe.name}        (the app; updater downloads this)")
print(f"  - {engine_zip.name}  (the engine; the app downloads this on first run)")
sys.exit(0)
