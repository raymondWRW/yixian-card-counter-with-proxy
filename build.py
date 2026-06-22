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

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name", "YiXianCounter",
    *icon_arg,
    # The main app's web/ folder + the shared proxy/ + the yisim bundle.
    "--add-data", f"web{SEP}web",
    "--add-data", f"proxy{SEP}proxy",
    "--add-data", f"tools{SEP}tools",
    # frida capture agent (loaded by runtime.start_frida_capture).
    "--add-data", f"native_hud/_build/capture.agent.js{SEP}native_hud/_build",
    "--collect-all", "frida",
    "--collect-all", "blackboxprotobuf",
    "--collect-all", "webview",
    "--hidden-import", "addon",
    "--hidden-import", "shadow_state",
    "--hidden-import", "game_state",
    "--hidden-import", "state_queue",
    "--hidden-import", "card_names",
    "--hidden-import", "battle_log",
    "--hidden-import", "decoder",
    "--hidden-import", "msgpack",
    "--collect-all", "msgpack",
    "--hidden-import", "updater",
    "--hidden-import", "version",
    "--hidden-import", "lingyu_merge",
    "--hidden-import", "proxy_view",
    "--hidden-import", "runtime",
    "--hidden-import", "frida",
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
for d in ("build", "dist"):
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
