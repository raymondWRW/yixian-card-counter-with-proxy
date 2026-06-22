// Compile-time stub for Cysharp UniTask. At runtime ILRuntime binds to the game's
// REAL UniTask (native); this exists ONLY so csc can resolve UniTask<T> return types.
namespace Cysharp.Threading.Tasks
{
    public struct UniTask { }
    public struct UniTask<T> { }
}
