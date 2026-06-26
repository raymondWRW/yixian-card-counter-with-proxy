#!/usr/bin/env bash
# Reproducible build for the Yi Xian Oracle (this project's standalone layout).
#
# One-time prereqs (already satisfied on this machine, listed for portability):
#   - .NET 8 SDK              (winget install Microsoft.DotNet.SDK.8)
#   - oracle/data/extracted/DarkSun.HotUpdate.dll + configs/*.dat   (extracted from the game, see extract step)
#   - oracle/tools/Il2CppDumper/v6.7.46/DummyDll/                   (Il2CppDumper on GameAssembly.dll+global-metadata)
#   - oracle/ILRuntime/Dependencies/netstandard2.0/*.dll           (ILRuntime fork of Mono.Cecil)
#
# Re-extracting game data after a game update (regenerates DLL + configs):
#   python tools/extract_game_data.py        # (the UnityPy extractor used during setup)
#
# Usage: bash oracle/build.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="/c/Program Files/dotnet:$PATH"

# The facade build script word-splits on spaces in paths, so build facades in a space-free temp then copy.
TMP="$(mktemp -d "/c/Users/$USER/AppData/Local/Temp/oracle_facades.XXXXXX" 2>/dev/null || echo /tmp/oracle_facades)"
echo "[1/4] building hand-written facades -> $TMP"
bash "$HERE/UnityStubs/build-facades.sh" "$TMP" >/dev/null
mkdir -p "$HERE/UnityStubs/bin/facades"
cp "$TMP"/*.dll "$HERE/UnityStubs/bin/facades/"
echo "      $(ls "$HERE/UnityStubs/bin/facades"/*.dll | wc -l) facade DLLs"

echo "[2/4] building Oracle.exe (Release)"
dotnet build -c Release -nologo "$HERE/Oracle/Oracle.csproj" | grep -E "Build succeeded|error" || true

echo "[3/4] generating complete facade set from DummyDll (facades-gen)"
"$HERE/Oracle/bin/Release/net8.0/Oracle.exe" --gen-facades 2>&1 | grep -E "generated" || true

echo "[4/4] smoke test (records sweep over a few of YOUR real games)"
SWEEP="$(mktemp -d)"; REC_ROOT="/c/Users/$USER/AppData/LocalLow/DarkSunStudio/YiXianPai/userLocalDatas"
n=0; for f in $(ls "$REC_ROOT"/*/recentBattleDatas/*.bin 2>/dev/null | head -20); do cp "$f" "$SWEEP/"; n=$((n+1)); done
if [ "$n" -gt 0 ]; then
  "$HERE/Oracle/bin/Release/net8.0/Oracle.exe" --records-dir "$SWEEP" --results-out "$SWEEP/_results.json" 2>&1 | grep "NATIVE SWEEP"
else
  echo "      (no local game records found to smoke-test)"
fi
echo "DONE. Warm worker: python oracle/scripts/oracle_pool.py  |  serve: Oracle.exe --serve"
