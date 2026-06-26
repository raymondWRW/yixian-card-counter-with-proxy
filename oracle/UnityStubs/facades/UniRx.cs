// UniRx facade
using System;

namespace UniRx
{
    // Real UniRx builds on the BCL System.IObservable<T>/System.IObserver<T>; the game DLL's
    // tokens reference those directly. Implement them (not homemade interfaces) so reactive
    // values flow through Subscribe/Where/Select without "cannot convert" errors.
    public class Subject<T> : System.IObservable<T>, System.IObserver<T>, IDisposable { public IDisposable Subscribe(System.IObserver<T> o) => Disposable.Empty; public void OnNext(T v) { } public void OnError(Exception e) { } public void OnCompleted() { } public void Dispose() { } }
    public class ReactiveProperty<T> : System.IObservable<T>, IDisposable { public T Value { get; set; } public ReactiveProperty() { } public ReactiveProperty(T v) { Value = v; } public IDisposable Subscribe(System.IObserver<T> o) => Disposable.Empty; public void Dispose() { } }
    // Typed ReactiveProperty subclasses referenced directly by the game DLL.
    public class BoolReactiveProperty : ReactiveProperty<bool> { public BoolReactiveProperty() { } public BoolReactiveProperty(bool v) : base(v) { } }
    public class IntReactiveProperty : ReactiveProperty<int> { public IntReactiveProperty() { } public IntReactiveProperty(int v) : base(v) { } }
    public class FloatReactiveProperty : ReactiveProperty<float> { public FloatReactiveProperty() { } public FloatReactiveProperty(float v) : base(v) { } }
    public class StringReactiveProperty : ReactiveProperty<string> { public StringReactiveProperty() { } public StringReactiveProperty(string v) : base(v) { } }
    public class ReactiveCollection<T> : System.Collections.Generic.List<T> { }
    public class CompositeDisposable : IDisposable { public void Add(IDisposable i) { } public void Dispose() { } }
    public static class Disposable { public static IDisposable Empty { get; } = new EmptyD(); private class EmptyD : IDisposable { public void Dispose() { } } public static IDisposable Create(Action a) => Empty; }
    public static class Observable { public static System.IObservable<long> Timer(TimeSpan d) => new Subject<long>(); public static System.IObservable<long> Interval(TimeSpan p) => new Subject<long>(); public static System.IObservable<T> Return<T>(T v) => new Subject<T>(); public static System.IObservable<System.Reactive.Unit> EveryUpdate() => new Subject<System.Reactive.Unit>(); }
    public static class ObservableExtensions
    {
        public static IDisposable Subscribe<T>(this System.IObservable<T> s, Action<T> n) => Disposable.Empty;
        public static IDisposable Subscribe<T>(this System.IObservable<T> s, Action<T> n, Action<Exception> e) => Disposable.Empty;
        public static IDisposable Subscribe<T>(this System.IObservable<T> s) => Disposable.Empty;
        public static System.IObservable<T> Where<T>(this System.IObservable<T> s, Func<T, bool> p) => s;
        public static System.IObservable<R> Select<T, R>(this System.IObservable<T> s, Func<T, R> sel) => new Subject<R>();
        public static IDisposable AddTo<T>(this T d, UnityEngine.Component c) where T : IDisposable => d;
    }
}
namespace System.Reactive { public struct Unit : IEquatable<Unit> { public static Unit Default => default; public bool Equals(Unit o) => true; public override bool Equals(object o) => o is Unit; public override int GetHashCode() => 0; } }
