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
# Publish a self-contained Oracle.exe (.NET runtime included) + bundle the facades, auto_patch,
# and Il2CppDumper. We do NOT bundle the game DLL/configs — oracle_bootstrap extracts those from
# the user's own install at first run (no game-code redistribution; auto-current with patches).
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

# Stamp the bundled facades-gen with the builder's GameAssembly key, so a user on the SAME game
# version reuses these facades; a different version triggers a self-heal regen (Il2CppDumper).
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

oracle_data = [
    ("_oracle_pub", "oracle/Oracle"),                                  # self-contained Oracle.exe + runtime + Cecil
    ("oracle/UnityStubs/bin/facades", "oracle/UnityStubs/bin/facades"),         # hand facades
    ("oracle/UnityStubs/bin/facades-gen", "oracle/UnityStubs/bin/facades-gen"), # generated facades (+ .gakey)
    ("oracle/auto_patch.json", "oracle"),
    ("oracle/scripts/oracle_pool.py", "oracle/scripts"),               # warm-worker manager (oracle_sim imports it)
    ("oracle/tools/Il2CppDumper/v6.7.46/Il2CppDumper.exe", "oracle/tools/Il2CppDumper/v6.7.46"),
    ("oracle/tools/Il2CppDumper/v6.7.46/config.json", "oracle/tools/Il2CppDumper/v6.7.46"),
]
oracle_args = []
for src, dst in oracle_data:
    oracle_args += ["--add-data", f"{src}{SEP}{dst}"]

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name", "YiXianCounter",
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

built_exe = HERE / "dist" / "YiXianCounter.exe"
target_exe = HERE / "YiXianCounter.exe"
if built_exe.exists():
    if target_exe.exists():
        target_exe.unlink()
    shutil.move(str(built_exe), str(target_exe))
for d in ("build", "dist", "_oracle_pub"):
    shutil.rmtree(HERE / d, ignore_errors=True)
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

print(f"\nBuilt: {target_exe}")
print(f"Share folder ready: {share}")
print(f"\n── Release SHA256 ──")
print(f"  version: {VERSION}")
print(f"  sha256:  {sha256}")
print("\nPaste this into dist_share/version.json:")
print(
    "{\n"
    f'  "version": "{VERSION}",\n'
    f'  "url": "https://gitee.com/hiddensquid12321/yixian-card-counter-with-proxy/releases/download/main-v{VERSION}/YiXianCounter.exe",\n'
    f'  "sha256": "{sha256}",\n'
    '  "notes": "What changed in this release."\n'
    "}"
)
print("\nThen create Gitee Release tagged 'main-v" + VERSION + "' and attach the exe.")
sys.exit(0)
