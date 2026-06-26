#!/usr/bin/env bash
# Build individual stub DLLs with correct assembly names.
# Each DLL satisfies a dependency of DarkSun.HotUpdate.dll.
#
# Usage: bash build-facades.sh [output-dir]
# Default output: ./bin/facades/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Auto-discover the installed SDK's csc.dll and the net8.0 reference pack (versions drift across updates).
DOTNET_ROOT="${DOTNET_ROOT:-C:/Program Files/dotnet}"
CSC_DLL="$(ls -d "$DOTNET_ROOT"/sdk/*/Roslyn/bincore/csc.dll 2>/dev/null | sort -V | tail -1)"
OUTPUT="${1:-$SCRIPT_DIR/bin/facades}"
FACADES_SRC="$SCRIPT_DIR/facades"
NETREF="$(ls -d "$DOTNET_ROOT"/packs/Microsoft.NETCore.App.Ref/*/ref/net8.0 2>/dev/null | sort -V | tail -1)"

mkdir -p "$OUTPUT"

echo "Building facade stub DLLs..."
echo "Output: $OUTPUT"
echo ""

# Compile each facade source into a DLL with the correct assembly name
compile_facade() {
    local name="$1"
    local src="$2"
    local refs="${3:-}"

    local ref_args=""
    if [ -n "$refs" ]; then
        for r in $refs; do
            ref_args="$ref_args -reference:$r"
        done
    fi

    dotnet "$CSC_DLL" -nologo -target:library -nostdlib \
        -reference:"$NETREF/System.Runtime.dll" \
        -reference:"$NETREF/System.Collections.dll" \
        -reference:"$NETREF/System.Runtime.InteropServices.dll" \
        -reference:"$NETREF/System.Threading.dll" \
        -reference:"$NETREF/System.Threading.Tasks.dll" \
        $ref_args \
        -nowarn:CS0649,CS8618,CS0067,CS0169,CS0108,CS0114,CS1998,CS0162 \
        -out:"$OUTPUT/$name.dll" \
        "$src" 2>&1

    if [ $? -eq 0 ]; then
        echo "  OK: $name.dll"
    else
        echo "  FAIL: $name.dll"
    fi
}

# Build in dependency order:
# 1. UnityEngine.CoreModule (base types, no deps)
# 2. Everything else (may reference CoreModule)

echo "--- Pass 1: Core assemblies ---"
compile_facade "UnityEngine.CoreModule" "$FACADES_SRC/UnityEngine.CoreModule.cs"
compile_facade "UnityEngine" "$FACADES_SRC/UnityEngine.cs" "$OUTPUT/UnityEngine.CoreModule.dll"

echo ""
echo "--- Pass 2: UI and framework assemblies ---"
compile_facade "UnityEngine.UI" "$FACADES_SRC/UnityEngine.UI.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.ParticleSystemModule" "$FACADES_SRC/UnityEngine.ParticleSystemModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.Purchasing" "$FACADES_SRC/UnityEngine.Purchasing.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.IMGUIModule" "$FACADES_SRC/UnityEngine.IMGUIModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.TextRenderingModule" "$FACADES_SRC/UnityEngine.TextRenderingModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.PhysicsModule" "$FACADES_SRC/UnityEngine.PhysicsModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.Physics2DModule" "$FACADES_SRC/UnityEngine.Physics2DModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.AnimationModule" "$FACADES_SRC/UnityEngine.AnimationModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.AudioModule" "$FACADES_SRC/UnityEngine.AudioModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.ImageConversionModule" "$FACADES_SRC/UnityEngine.ImageConversionModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.InputLegacyModule" "$FACADES_SRC/UnityEngine.InputLegacyModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.JSONSerializeModule" "$FACADES_SRC/UnityEngine.JSONSerializeModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.UnityWebRequestModule" "$FACADES_SRC/UnityEngine.UnityWebRequestModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.UIModule" "$FACADES_SRC/UnityEngine.UIModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "UnityEngine.AssetBundleModule" "$FACADES_SRC/UnityEngine.AssetBundleModule.cs" "$OUTPUT/UnityEngine.CoreModule.dll"

echo ""
echo "--- Pass 3: Third-party assemblies ---"
compile_facade "UniTask" "$FACADES_SRC/UniTask.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "wProtobuf" "$FACADES_SRC/wProtobuf.cs"
compile_facade "GameClient" "$FACADES_SRC/GameClient.cs" "$OUTPUT/wProtobuf.dll"
compile_facade "UnityEngine.Rendering" "$FACADES_SRC/UnityEngine.Rendering.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "DarkSun.Utility" "$FACADES_SRC/DarkSun.Utility.cs" "$OUTPUT/UnityEngine.CoreModule.dll $OUTPUT/wProtobuf.dll"
compile_facade "DarkSun.UI" "$FACADES_SRC/DarkSun.UI.cs" "$OUTPUT/UnityEngine.CoreModule.dll $OUTPUT/DarkSun.Utility.dll"
compile_facade "DOTween" "$FACADES_SRC/DOTween.cs" "$OUTPUT/UnityEngine.CoreModule.dll $OUTPUT/UniTask.dll"
compile_facade "Spine" "$FACADES_SRC/Spine.cs"
compile_facade "spine-csharp" "$FACADES_SRC/spine-csharp.cs"
compile_facade "Spine.Unity" "$FACADES_SRC/Spine.Unity.cs" "$OUTPUT/UnityEngine.CoreModule.dll $OUTPUT/spine-csharp.dll"
compile_facade "spine-unity" "$FACADES_SRC/spine-unity.cs" "$OUTPUT/UnityEngine.CoreModule.dll $OUTPUT/spine-csharp.dll"
compile_facade "UniRx" "$FACADES_SRC/UniRx.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "DarkTonic.MasterAudio" "$FACADES_SRC/DarkTonic.MasterAudio.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "Cinemachine" "$FACADES_SRC/Cinemachine.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "Unity.ResourceManager" "$FACADES_SRC/Unity.ResourceManager.cs"
compile_facade "Unity.Addressables" "$FACADES_SRC/Unity.Addressables.cs" "$OUTPUT/UnityEngine.CoreModule.dll $OUTPUT/Unity.ResourceManager.dll"
compile_facade "Unity.TextMeshPro" "$FACADES_SRC/Unity.TextMeshPro.cs" "$OUTPUT/UnityEngine.CoreModule.dll $OUTPUT/UnityEngine.UI.dll"
compile_facade "TMPro" "$FACADES_SRC/TMPro.cs" "$OUTPUT/UnityEngine.CoreModule.dll $OUTPUT/UnityEngine.UI.dll"
compile_facade "RailSDK" "$FACADES_SRC/RailSDK.cs"
compile_facade "TapTap.Bootstrap.Runtime" "$FACADES_SRC/TapTap.Bootstrap.Runtime.cs"
compile_facade "TapTap.Common" "$FACADES_SRC/TapTap.Common.cs"
compile_facade "TapTap.Login" "$FACADES_SRC/TapTap.Login.cs"
compile_facade "TapTap.Achievement" "$FACADES_SRC/TapTap.Achievement.cs"
compile_facade "DarkSun.Login" "$FACADES_SRC/DarkSun.Login.cs" "$OUTPUT/UnityEngine.CoreModule.dll"
compile_facade "Facepunch.Steamworks.Win64" "$FACADES_SRC/Facepunch.Steamworks.Win64.cs"

echo ""
echo "--- Pass 4: auto-generated facades (references all of the above) ---"
if [ -f "$FACADES_SRC/Generated.cs" ]; then
    compile_facade "Generated" "$FACADES_SRC/Generated.cs" "$(ls "$OUTPUT"/*.dll | grep -v '/Generated.dll' | tr '\n' ' ')"
fi

echo ""
echo "--- Done ---"
ls -la "$OUTPUT"/*.dll 2>/dev/null | wc -l
echo "facade DLLs built."
