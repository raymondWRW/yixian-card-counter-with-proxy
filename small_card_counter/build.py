"""
Build YiXianCounterLite.exe via PyInstaller.

Run from this folder:
  ..\.venv\Scripts\python.exe build.py
"""
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
spec = HERE / "YiXianCounterLite.spec"
if spec.exists():
    spec.unlink()

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name", "YiXianCounterLite",
    "--icon", "icon.ico",
    "--add-data", f"web{SEP}web",
    "--add-data", f"proxy{SEP}proxy",
    "--add-data", f"tools{SEP}tools",
    "--collect-all", "mitmproxy",
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
    # Auto-update modules — must ship with the bundle so the bundled exe
    # can fetch the Gitee manifest on launch and self-replace when newer.
    "--hidden-import", "updater",
    "--hidden-import", "version",
    "app.py",
]
print("Running:", " ".join(cmd))
result = subprocess.run(cmd, cwd=str(HERE))
if result.returncode != 0:
    sys.exit(result.returncode)

# Move the produced exe out of dist/ and into the folder root, clean junk.
built_exe = HERE / "dist" / "YiXianCounterLite.exe"
target_exe = HERE / "YiXianCounterLite.exe"
if built_exe.exists():
    if target_exe.exists():
        target_exe.unlink()
    shutil.move(str(built_exe), str(target_exe))
for d in ("build", "dist"):
    shutil.rmtree(HERE / d, ignore_errors=True)
if spec.exists():
    spec.unlink()

# Refresh the share folder so it always has the latest exe alongside the
# Setup.bat / Run.bat / README.txt helpers (kept in the folder, never
# overwritten by the build).
share = HERE / "dist_share"
share.mkdir(exist_ok=True)
shutil.copy2(str(target_exe), str(share / "YiXianCounterLite.exe"))

# Compute SHA256 of the built exe so the release manifest stays consistent
# with the binary. Print a ready-to-paste version.json snippet — the user
# only has to swap the Gitee URL and commit it to the repo.
import hashlib
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
print("\nPaste this into dist_share/version.json (replace the Gitee URL):")
print(
    "{\n"
    f'  "version": "{VERSION}",\n'
    f'  "url": "https://gitee.com/hiddensquid12321/yixian-card-counter-with-proxy/releases/download/v{VERSION}/YiXianCounterLite.exe",\n'
    f'  "sha256": "{sha256}",\n'
    '  "notes": "What changed in this release."\n'
    "}"
)
sys.exit(0)
