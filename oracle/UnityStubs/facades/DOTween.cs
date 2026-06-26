// DOTween facade
using System;
using UnityEngine;

namespace DG.Tweening
{
    public enum Ease { Unset, Linear, InSine, OutSine, InOutSine, InQuad, OutQuad, InOutQuad, InCubic, OutCubic, InOutCubic, InQuart, OutQuart, InOutQuart, InQuint, OutQuint, InOutQuint, InExpo, OutExpo, InOutExpo, InCirc, OutCirc, InOutCirc, InElastic, OutElastic, InOutElastic, InBack, OutBack, InOutBack, InBounce, OutBounce, InOutBounce, Flash, InFlash, OutFlash, InOutFlash }
    public enum LoopType { Restart, Yoyo, Incremental }
    public enum RotateMode { Fast, FastBeyond360, WorldAxisAdd, LocalAxisAdd }
    public enum UpdateType { Normal, Late, Fixed, Manual }
    public enum LogBehaviour { Default, Verbose, ErrorsOnly }

    public abstract class Tween
    {
        public float fullPosition { get; set; }
        public bool IsActive() => false; public bool IsComplete() => true; public bool IsPlaying() => false;
        public void Kill(bool c = false) { } public void Complete(bool c = false) { }
        public void Pause() { } public void Play() { } public void PlayBackwards() { } public void PlayForward() { }
        public void Restart(bool d = true, float c = -1) { } public void Rewind(bool d = true) { } public void Flip() { }
        public void Goto(float t, bool a = false) { }
    }

    public class Tweener : Tween { }
    public class Sequence : Tween
    {
        public Sequence Append(Tween t) => this; public Sequence AppendCallback(TweenCallback c) => this;
        public Sequence AppendInterval(float i) => this; public Sequence Insert(float p, Tween t) => this;
        public Sequence InsertCallback(float p, TweenCallback c) => this; public Sequence Join(Tween t) => this;
        public Sequence Prepend(Tween t) => this; public Sequence PrependCallback(TweenCallback c) => this;
        public Sequence PrependInterval(float i) => this;
    }

    public delegate void TweenCallback();
    public delegate void TweenCallback<in T>(T value);
    public delegate T DOGetter<out T>();
    public delegate void DOSetter<in T>(T v);

    public static class DOTween
    {
        public static Sequence Sequence() => new Sequence();
        public static int Kill(object t, bool c = false) => 0;
        public static bool IsTweening(object t, bool c = false) => false;
        public static Tweener To(DOGetter<float> g, DOSetter<float> s, float e, float d) => new Tweener();
        public static Tweener To(DOGetter<Vector3> g, DOSetter<Vector3> s, Vector3 e, float d) => new Tweener();
        public static Tweener To(DOGetter<Color> g, DOSetter<Color> s, Color e, float d) => new Tweener();
        public static void Init(bool? r = null, bool? s = null, LogBehaviour? l = null) { }
    }

    public static class TweenSettingsExtensions
    {
        public static T SetAutoKill<T>(this T t, bool a = true) where T : Tween => t;
        public static T SetDelay<T>(this T t, float d) where T : Tween => t;
        public static T SetEase<T>(this T t, Ease e) where T : Tween => t;
        public static T SetEase<T>(this T t, AnimationCurve c) where T : Tween => t;
        public static T SetId<T>(this T t, object id) where T : Tween => t;
        public static T SetLoops<T>(this T t, int l, LoopType lt = LoopType.Restart) where T : Tween => t;
        public static T SetRelative<T>(this T t) where T : Tween => t;
        public static T SetRelative<T>(this T t, bool r) where T : Tween => t;
        public static T SetTarget<T>(this T t, object tgt) where T : Tween => t;
        public static T SetUpdate<T>(this T t, UpdateType u, bool i = false) where T : Tween => t;
        public static T SetUpdate<T>(this T t, bool i) where T : Tween => t;
        public static T SetSpeedBased<T>(this T t) where T : Tween => t;
        public static T SetSpeedBased<T>(this T t, bool isSpeedBased) where T : Tween => t;
        public static T OnComplete<T>(this T t, TweenCallback a) where T : Tween => t;
        public static T OnKill<T>(this T t, TweenCallback a) where T : Tween => t;
        public static T OnStart<T>(this T t, TweenCallback a) where T : Tween => t;
        public static T OnUpdate<T>(this T t, TweenCallback a) where T : Tween => t;
        public static T OnStepComplete<T>(this T t, TweenCallback a) where T : Tween => t;
        public static T OnPlay<T>(this T t, TweenCallback a) where T : Tween => t;
        public static T From<T>(this T t) where T : Tween => t;
        public static T From<T>(this T t, bool r) where T : Tween => t;
        public static Tweener SetOptions(this Tweener t, bool s) => t;
    }

    public static class ShortcutExtensions
    {
        public static int DOKill(this Component t, bool c = false) => 0;
        public static DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions> DOMove(this Transform t, Vector3 e, float d, bool s = false) => new DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions>();
        public static DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions> DOMoveX(this Transform t, float e, float d, bool s = false) => new DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions>();
        public static DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions> DOMoveY(this Transform t, float e, float d, bool s = false) => new DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions>();
        public static DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions> DOMoveZ(this Transform t, float e, float d, bool s = false) => new DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions>();
        public static DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions> DOLocalMove(this Transform t, Vector3 e, float d, bool s = false) => new DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions>();
        public static DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions> DOLocalMoveX(this Transform t, float e, float d, bool s = false) => new DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions>();
        public static DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions> DOLocalMoveY(this Transform t, float e, float d, bool s = false) => new DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions>();
        public static DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions> DOLocalMoveZ(this Transform t, float e, float d, bool s = false) => new DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions>();
        public static DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions> DOScale(this Transform t, Vector3 e, float d) => new DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions>();
        public static DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions> DOScale(this Transform t, float e, float d) => new DG.Tweening.Core.TweenerCore<Vector3, Vector3, DG.Tweening.Plugins.Options.VectorOptions>();
        public static Tweener DOScaleX(this Transform t, float e, float d) => new Tweener();
        public static Tweener DOScaleY(this Transform t, float e, float d) => new Tweener();
        public static Tweener DORotate(this Transform t, Vector3 e, float d, RotateMode m = RotateMode.Fast) => new Tweener();
        public static Tweener DOLocalRotate(this Transform t, Vector3 e, float d, RotateMode m = RotateMode.Fast) => new Tweener();
        public static Tweener DOPunchPosition(this Transform t, Vector3 p, float d, int v = 10, float e = 1) => new Tweener();
        public static Tweener DOPunchScale(this Transform t, Vector3 p, float d, int v = 10, float e = 1) => new Tweener();
        public static Tweener DOShakePosition(this Transform t, float d, float s = 1, int v = 10) => new Tweener();
        public static Tweener DOShakePosition(this Transform t, float d, float s, int v, float r, bool snapping = false, bool fadeOut = true) => new Tweener();
        public static Tweener DOShakePosition(this Transform t, float d, Vector3 s, int v = 10, float r = 90, bool snapping = false, bool fadeOut = true) => new Tweener();
        public static Tweener DOShakeScale(this Transform t, float d, float s = 1, int v = 10, float r = 90, bool fadeOut = true) => new Tweener();
        public static Tweener DOShakeRotation(this Transform t, float d, float s = 90, int v = 10, float r = 90, bool fadeOut = true) => new Tweener();
        public static Tweener DOColor(this SpriteRenderer t, Color e, float d) => new Tweener();
        public static Tweener DOFade(this SpriteRenderer t, float e, float d) => new Tweener();
        public static Tweener DOColor(this Material t, Color e, float d) => new Tweener();
        public static Tweener DOColor(this Material t, Color e, string p, float d) => new Tweener();
        public static Tweener DOFade(this Material t, float e, float d) => new Tweener();
        public static Tweener DOFloat(this Material t, float e, string p, float d) => new Tweener();
        public static Tweener DOOrthoSize(this Camera t, float e, float d) => new Tweener();
    }

    public static class ShortcutExtensionsUI
    {
        public static Tweener DOFade(this CanvasGroup t, float e, float d) => new Tweener();
        public static Tweener DOAnchorPos(this RectTransform t, Vector2 e, float d, bool s = false) => new Tweener();
        public static Tweener DOAnchorPosX(this RectTransform t, float e, float d, bool s = false) => new Tweener();
        public static Tweener DOAnchorPosY(this RectTransform t, float e, float d, bool s = false) => new Tweener();
        public static Tweener DOSizeDelta(this RectTransform t, Vector2 e, float d, bool s = false) => new Tweener();
    }

    public static class DOVirtual
    {
        public static Tweener Float(float f, float t, float d, TweenCallback<float> u) => new Tweener();
        public static Tweener DelayedCall(float d, TweenCallback c, bool i = true) => new Tweener();
    }

    // DOTweenModuleUI — UI-specific tween shortcuts referenced by game code
    public static class DOTweenModuleUI
    {
        public static DG.Tweening.Core.TweenerCore<float, float, DG.Tweening.Plugins.Options.FloatOptions> DOFade(UnityEngine.CanvasGroup t, float e, float d) => new DG.Tweening.Core.TweenerCore<float, float, DG.Tweening.Plugins.Options.FloatOptions>();
        public static DG.Tweening.Core.TweenerCore<UnityEngine.Vector2, UnityEngine.Vector2, DG.Tweening.Plugins.Options.VectorOptions> DOAnchorPos(UnityEngine.RectTransform t, UnityEngine.Vector2 e, float d, bool s = false) => new DG.Tweening.Core.TweenerCore<UnityEngine.Vector2, UnityEngine.Vector2, DG.Tweening.Plugins.Options.VectorOptions>();
    }
}

namespace DG.Tweening.Core
{
    public class TweenerCore<T1, T2, TPlugOptions> : DG.Tweening.Tweener where TPlugOptions : struct
    {
        public TweenerCore<T1, T2, TPlugOptions> ChangeStartValue(T1 newStartValue, float newDuration = -1) => this;
    }

    // DOTween's getter/setter delegates also live under DG.Tweening.Core in the game DLL's tokens.
    public delegate T DOGetter<out T>();
    public delegate void DOSetter<in T>(T value);
}

namespace DG.Tweening.Plugins.Options
{
    public struct VectorOptions { }
    public struct FloatOptions { }
    public struct StringOptions { }
    public struct ColorOptions { }
}

// UniTask's DOTween integration. The game awaits tweens via DOTweenExtensions.ToUniTask(tween).
// In the game DLL this type lives in the GLOBAL namespace (TypeRef.FullName == "DOTweenExtensions"),
// so it must be declared globally here for ILRuntime to resolve the token.
// Headless: tweens never animate, so every tween-task is already completed (default UniTask,
// whose awaiter reports IsCompleted == true) — the awaiting state machine runs straight through.
public enum TweenCancelBehaviour
{
    Kill, KillWithCompleteCallback, Complete, CompleteWithSeqCallback,
    CancelAwait, KillAndCancelAwait, KillWithCompleteCallbackAndCancelAwait,
    CompleteAndCancelAwait, CompleteWithSeqCallbackAndCancelAwait
}

public static class DOTweenExtensions
{
    // The game's own single-arg wrapper (matched by exact IL signature: ToUniTask(Tween)).
    public static Cysharp.Threading.Tasks.UniTask ToUniTask(DG.Tweening.Tween tween) => default;
    public static Cysharp.Threading.Tasks.UniTask AsyncWaitForCompletion(this DG.Tweening.Tween tween) => default;
    public static Cysharp.Threading.Tasks.UniTask AsyncWaitForKill(this DG.Tweening.Tween tween) => default;
    public static Cysharp.Threading.Tasks.UniTask AsyncWaitForPause(this DG.Tweening.Tween tween) => default;
    public static Cysharp.Threading.Tasks.UniTask AsyncWaitForRewind(this DG.Tweening.Tween tween) => default;
    public static Cysharp.Threading.Tasks.UniTask AsyncWaitForElapsedLoops(this DG.Tweening.Tween tween, int elapsedLoops) => default;
    public static Cysharp.Threading.Tasks.UniTask AsyncWaitForPosition(this DG.Tweening.Tween tween, float position) => default;
}
