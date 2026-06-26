// UniTask facade
using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Threading;

namespace Cysharp.Threading.Tasks
{
    public enum PlayerLoopTiming { Initialization, LastInitialization, EarlyUpdate, LastEarlyUpdate, FixedUpdate, LastFixedUpdate, PreUpdate, LastPreUpdate, Update, LastUpdate, PreLateUpdate, LastPreLateUpdate, PostLateUpdate, LastPostLateUpdate, TimeUpdate, LastTimeUpdate }
    public enum DelayType { DeltaTime = 0, UnscaledDeltaTime = 1, Realtime = 2 }

    [AsyncMethodBuilder(typeof(CompilerServices.AsyncUniTaskMethodBuilder))]
    public readonly struct UniTask
    {
        public static UniTask CompletedTask => default;
        // Must return the NESTED UniTask.Awaiter — the game's IL token is "UniTask/Awaiter UniTask::GetAwaiter()"
        public Awaiter GetAwaiter() => new Awaiter();
        // Delay overloads must match the real IL signatures exactly (dump.cs ~564071): each ends with a
        // CancellationToken then a trailing `bool cancelImmediately`, and there are DelayType variants.
        public static UniTask Delay(int ms, bool ignoreTimeScale = false, PlayerLoopTiming timing = PlayerLoopTiming.Update, CancellationToken ct = default, bool cancelImmediately = false) => default;
        public static UniTask Delay(TimeSpan ts, bool ignoreTimeScale = false, PlayerLoopTiming timing = PlayerLoopTiming.Update, CancellationToken ct = default, bool cancelImmediately = false) => default;
        public static UniTask Delay(int ms, DelayType delayType, PlayerLoopTiming timing = PlayerLoopTiming.Update, CancellationToken ct = default, bool cancelImmediately = false) => default;
        public static UniTask Delay(TimeSpan ts, DelayType delayType, PlayerLoopTiming timing = PlayerLoopTiming.Update, CancellationToken ct = default, bool cancelImmediately = false) => default;
        public static UniTask DelayFrame(int frames, PlayerLoopTiming timing = PlayerLoopTiming.Update, CancellationToken ct = default, bool cancelImmediately = false) => default;
        // Real UniTask.Yield overloads (dump.cs ~564021): the no-arg + PlayerLoopTiming forms return
        // YieldAwaitable (already-completed here so awaits resolve synchronously); only the
        // CancellationToken forms return UniTask. The game's IL binds to the EXACT signature (no C#
        // default-arg expansion), so each overload must be present with its true return type.
        public static YieldAwaitable Yield() => default;
        public static YieldAwaitable Yield(PlayerLoopTiming timing) => default;
        public static UniTask Yield(CancellationToken cancellationToken, bool cancelImmediately = false) => default;
        public static UniTask Yield(PlayerLoopTiming timing, CancellationToken cancellationToken, bool cancelImmediately = false) => default;
        // WaitUntil/WaitWhile: headless the predicate condition (animation done, etc.) is treated as
        // already satisfied — return a completed UniTask so the await resolves immediately.
        public static UniTask WaitUntil(Func<bool> predicate, PlayerLoopTiming timing = PlayerLoopTiming.Update, CancellationToken cancellationToken = default, bool cancelImmediately = false) => default;
        public static UniTask WaitWhile(Func<bool> predicate, PlayerLoopTiming timing = PlayerLoopTiming.Update, CancellationToken cancellationToken = default, bool cancelImmediately = false) => default;
        public static UniTask WhenAll(params UniTask[] tasks) => default;
        public static UniTask<T[]> WhenAll<T>(params UniTask<T>[] tasks) => default;
        public static UniTask WhenAll(IEnumerable<UniTask> tasks) => default;
        public static UniTask<T[]> WhenAll<T>(IEnumerable<UniTask<T>> tasks) => default;
        public static UniTask RunOnThreadPool(Action action) => default;
        public static UniTask SwitchToMainThread() => default;
        public static UniTask SwitchToThreadPool() => default;
        public static UniTask Never(CancellationToken ct = default) => default;
        public static UniTask<T> FromResult<T>(T result) => new UniTask<T>(result);
        public UniTask ContinueWith(Action c) => default;
        public UniTask ContinueWith(Func<UniTask> c) => default;
        public UniTask SuppressCancellationThrow() => default;

        // Nested Awaiter that IS the top-level Awaiter (same type, avoids conversion errors)
        public new struct Awaiter : ICriticalNotifyCompletion
        {
            public bool IsCompleted => true;
            public void GetResult() { }
            public void OnCompleted(Action c) { if (c != null) c(); }
            public void UnsafeOnCompleted(Action c) { if (c != null) c(); }
            public static implicit operator Cysharp.Threading.Tasks.Awaiter(Awaiter a) => new Cysharp.Threading.Tasks.Awaiter();
        }
    }

    [AsyncMethodBuilder(typeof(CompilerServices.AsyncUniTaskMethodBuilder<>))]
    public readonly struct UniTask<T>
    {
        private readonly T _result;
        public UniTask(T result) { _result = result; }
        public Awaiter GetAwaiter() => new Awaiter(_result);
        public UniTask ContinueWith(Action<T> c) => default;
        public UniTask<U> ContinueWith<U>(Func<T, U> c) => default;
        public UniTask SuppressCancellationThrow() => default;

        public readonly struct Awaiter : ICriticalNotifyCompletion
        {
            private readonly T _result;
            public Awaiter(T result) { _result = result; }
            public bool IsCompleted => true;
            public T GetResult() => _result;
            public void OnCompleted(Action c) { if (c != null) c(); }
            public void UnsafeOnCompleted(Action c) { if (c != null) c(); }
        }
    }

    public readonly struct UniTaskVoid { public void Forget() { } }

    // await UniTask.Yield() returns a YieldAwaitable with its own nested Awaiter.
    public readonly struct YieldAwaitable
    {
        public Awaiter GetAwaiter() => new Awaiter();
        public readonly struct Awaiter : ICriticalNotifyCompletion
        {
            public bool IsCompleted => true;
            public void GetResult() { }
            public void OnCompleted(Action c) { if (c != null) c(); }
            public void UnsafeOnCompleted(Action c) { if (c != null) c(); }
        }
    }

    public interface IUniTaskSource { UniTaskStatus GetStatus(short token); void GetResult(short token); UniTaskStatus UnsafeGetStatus(); void OnCompleted(Action<object> continuation, object state, short token); }
    public interface IUniTaskSource<out T> : IUniTaskSource { new T GetResult(short token); }
    public enum UniTaskStatus { Pending, Succeeded, Faulted, Canceled }

    public static class UniTaskExtensions
    {
        public static void Forget(this UniTask task) { }
        public static void Forget(this UniTaskVoid task) { }
        // Headless the inner task is already complete, so "timeout?" is false — return a completed
        // UniTask<bool>=false (and <(false, default)> for the typed form). Skips the timeout race entirely.
        public static UniTask<bool> TimeoutWithoutException(this UniTask task, TimeSpan timeout, DelayType delayType = DelayType.DeltaTime, PlayerLoopTiming timeoutCheckTiming = PlayerLoopTiming.Update, CancellationTokenSource taskCancellationTokenSource = null) => default;
        public static UniTask<System.ValueTuple<bool, T>> TimeoutWithoutException<T>(this UniTask<T> task, TimeSpan timeout, DelayType delayType = DelayType.DeltaTime, PlayerLoopTiming timeoutCheckTiming = PlayerLoopTiming.Update, CancellationTokenSource taskCancellationTokenSource = null) => default;
    }

    public class UniTaskCompletionSource : IUniTaskSource
    {
        public UniTask Task => default;
        public bool TrySetResult() => true;
        public bool TrySetException(Exception e) => true;
        public bool TrySetCanceled() => true;
        public UniTaskStatus GetStatus(short t) => UniTaskStatus.Succeeded;
        public void GetResult(short t) { }
        public UniTaskStatus UnsafeGetStatus() => UniTaskStatus.Succeeded;
        public void OnCompleted(Action<object> c, object s, short t) { }
    }

    public class UniTaskCompletionSource<T> : IUniTaskSource<T>
    {
        public UniTask<T> Task => default;
        public bool TrySetResult(T result) => true;
        public bool TrySetException(Exception e) => true;
        public bool TrySetCanceled() => true;
        public UniTaskStatus GetStatus(short t) => UniTaskStatus.Succeeded;
        public T GetResult(short t) => default;
        void IUniTaskSource.GetResult(short t) { }
        public UniTaskStatus UnsafeGetStatus() => UniTaskStatus.Succeeded;
        public void OnCompleted(Action<object> c, object s, short t) { }
    }
}

namespace Cysharp.Threading.Tasks.CompilerServices
{
    public struct AsyncUniTaskMethodBuilder
    {
        public UniTask Task => default;
        public static AsyncUniTaskMethodBuilder Create() => new AsyncUniTaskMethodBuilder();
        public void Start<T>(ref T sm) where T : IAsyncStateMachine { sm.MoveNext(); }
        public void SetStateMachine(IAsyncStateMachine sm) { }
        public void SetResult() { }
        public void SetException(Exception e) { }
        public void AwaitOnCompleted<TA, TS>(ref TA a, ref TS s) where TA : INotifyCompletion where TS : IAsyncStateMachine { a.OnCompleted(s.MoveNext); }
        public void AwaitUnsafeOnCompleted<TA, TS>(ref TA a, ref TS s) where TA : ICriticalNotifyCompletion where TS : IAsyncStateMachine { a.UnsafeOnCompleted(s.MoveNext); }
    }

    public struct AsyncUniTaskMethodBuilder<T>
    {
        // Result must survive struct copies: the async pattern calls SetResult on one copy of the
        // builder (the state machine's field) and reads Task on another (the outer method's local).
        // A plain field would be lost on copy, making every `async UniTask<T>` return default(T) —
        // which silently mis-returns typed results (e.g. CardActionExecuteResult.Failed = default,
        // dropping every card from the battle deck). Back the result with a shared reference cell so
        // all copies observe the same SetResult.
        private StrongBox<T> _box;
        public UniTask<T> Task => new UniTask<T>(_box != null ? _box.Value : default);
        public static AsyncUniTaskMethodBuilder<T> Create() => new AsyncUniTaskMethodBuilder<T> { _box = new StrongBox<T>() };
        public void Start<TS>(ref TS sm) where TS : IAsyncStateMachine => sm.MoveNext();
        public void SetStateMachine(IAsyncStateMachine sm) { }
        public void SetResult(T result) { (_box ??= new StrongBox<T>()).Value = result; }
        public void SetException(Exception e) { }
        public void AwaitOnCompleted<TA, TS>(ref TA a, ref TS s) where TA : INotifyCompletion where TS : IAsyncStateMachine { a.OnCompleted(s.MoveNext); }
        public void AwaitUnsafeOnCompleted<TA, TS>(ref TA a, ref TS s) where TA : ICriticalNotifyCompletion where TS : IAsyncStateMachine { a.UnsafeOnCompleted(s.MoveNext); }
    }

    public struct AsyncUniTaskVoidMethodBuilder
    {
        public UniTaskVoid Task => default;
        public static AsyncUniTaskVoidMethodBuilder Create() => new AsyncUniTaskVoidMethodBuilder();
        public void Start<T>(ref T sm) where T : IAsyncStateMachine => sm.MoveNext();
        public void SetStateMachine(IAsyncStateMachine sm) { }
        public void SetResult() { }
        public void SetException(Exception e) { }
        public void AwaitOnCompleted<TA, TS>(ref TA a, ref TS s) where TA : INotifyCompletion where TS : IAsyncStateMachine { a.OnCompleted(s.MoveNext); }
        public void AwaitUnsafeOnCompleted<TA, TS>(ref TA a, ref TS s) where TA : ICriticalNotifyCompletion where TS : IAsyncStateMachine { a.UnsafeOnCompleted(s.MoveNext); }
    }
}

namespace Cysharp.Threading.Tasks.Linq
{
    public interface IUniTaskAsyncEnumerable<out T> { }
    public interface IUniTaskAsyncEnumerator<out T> : IAsyncDisposable { T Current { get; } UniTask<bool> MoveNextAsync(); }
}

namespace Cysharp.Threading.Tasks.Triggers { }

// Unity integration awaiters
namespace Cysharp.Threading.Tasks
{
    // Awaiter for UnityWebRequestAsyncOperation
    public struct UnityWebRequestAsyncOperationAwaiter : System.Runtime.CompilerServices.ICriticalNotifyCompletion
    {
        public bool IsCompleted => true;
        public UnityEngine.Networking.UnityWebRequest GetResult() => new UnityEngine.Networking.UnityWebRequest();
        public void OnCompleted(Action c) { if (c != null) c(); }
        public void UnsafeOnCompleted(Action c) { if (c != null) c(); }
    }

    // Generic awaiter type referenced from compiled code
    public struct Awaiter : System.Runtime.CompilerServices.ICriticalNotifyCompletion
    {
        public bool IsCompleted => true;
        public void GetResult() { }
        public void OnCompleted(Action c) { if (c != null) c(); }
        public void UnsafeOnCompleted(Action c) { if (c != null) c(); }
    }

    // Generic awaiter — decompiled code references Awaiter<T> for typed async results
    public struct Awaiter<T> : System.Runtime.CompilerServices.ICriticalNotifyCompletion
    {
        public bool IsCompleted => true;
        public T GetResult() => default;
        public void OnCompleted(Action c) { if (c != null) c(); }
        public void UnsafeOnCompleted(Action c) { if (c != null) c(); }
    }
}
