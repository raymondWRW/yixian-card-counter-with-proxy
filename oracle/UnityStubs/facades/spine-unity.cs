// spine-unity facade — Spine.Unity types
using UnityEngine;

namespace Spine.Unity
{
    public class SkeletonAnimation : SkeletonRenderer
    {
        public Spine.AnimationState AnimationState { get; set; }
        public string AnimationName { get; set; }
        public bool loop { get; set; }
        public float timeScale { get; set; }
    }
    public class SkeletonRenderer : MonoBehaviour
    {
        public Spine.Skeleton Skeleton { get; set; }
        public SkeletonDataAsset SkeletonDataAsset { get; set; }
        public bool initialFlipX { get; set; } public bool initialFlipY { get; set; }
        public string initialSkinName { get; set; }
        public void Initialize(bool overwrite) { }
    }
    public class SkeletonGraphic : MonoBehaviour
    {
        public Spine.Skeleton Skeleton { get; set; }
        public Spine.AnimationState AnimationState { get; set; }
        public SkeletonDataAsset SkeletonDataAsset { get; set; }
        public string startingAnimation { get; set; } public bool startingLoop { get; set; }
        public float timeScale { get; set; }
        public void Initialize(bool overwrite) { }
        public void Freeze() { } public void Unfreeze() { }
    }
    public class SkeletonDataAsset : ScriptableObject { public Spine.SkeletonData GetSkeletonData(bool quiet) => null; }
    public class BoneFollower : MonoBehaviour { public string boneName { get; set; } public SkeletonRenderer skeletonRenderer { get; set; } }
    public static class SkeletonExtensions { public static void SetColor(this Spine.Skeleton s, UnityEngine.Color c) { } }
}
namespace Spine.Unity { public class SkeletonUtility : UnityEngine.MonoBehaviour {} public class SkeletonUtilityBone : UnityEngine.MonoBehaviour {} }
namespace Spine.Unity { public class SkeletonRenderTexture : UnityEngine.MonoBehaviour {} public class SkeletonRenderTextureBase : UnityEngine.MonoBehaviour {} }
public class GhostTrailEffectSkeletonRenderer : UnityEngine.MonoBehaviour {}
