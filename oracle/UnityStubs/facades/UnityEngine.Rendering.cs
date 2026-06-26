// UnityEngine.Rendering facade — post-processing Volume stack.
// Only needed so MonoBehaviours holding Volume fields (BattleManager) can instantiate;
// never exercised in headless combat.
using UnityEngine;

namespace UnityEngine.Rendering
{
    public class VolumeComponent { public bool active; }
    public class VolumeProfile
    {
        public bool TryGet<T>(ref T component) where T : VolumeComponent { component = default; return false; }
        public bool Has<T>() where T : VolumeComponent => false;
    }
    public class Volume : MonoBehaviour { public VolumeProfile profile { get; set; } = new VolumeProfile(); public float weight { get; set; } }
}

namespace UnityEngine.Rendering.Universal
{
    public class DepthOfField : UnityEngine.Rendering.VolumeComponent { }
}
