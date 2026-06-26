// Unity.ResourceManager facade
using System;

namespace UnityEngine.ResourceManagement.AsyncOperations
{
    public enum AsyncOperationStatus { None, Succeeded, Failed }
    public struct AsyncOperationHandle<T> { public T Result => default; public bool IsDone => true; public AsyncOperationStatus Status => AsyncOperationStatus.Succeeded; public float PercentComplete => 1; public event Action<AsyncOperationHandle<T>> Completed { add { } remove { } } }
    public struct AsyncOperationHandle { public object Result => null; public bool IsDone => true; }
}

namespace UnityEngine.ResourceManagement.ResourceLocations
{
    public interface IResourceLocation { string PrimaryKey { get; } string InternalId { get; } Type ResourceType { get; } }
}

namespace UnityEngine.ResourceManagement.ResourceProviders
{
    public struct SceneInstance { }
}
