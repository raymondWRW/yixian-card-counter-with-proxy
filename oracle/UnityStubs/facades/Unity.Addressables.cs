// Unity.Addressables facade — loads config .dat files from disk instead of Unity asset bundles
using System; using System.Collections.Generic; using System.IO; using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.ResourceManagement.AsyncOperations;
namespace UnityEngine.AddressableAssets
{
    public static class Addressables
    {
        /// Set this before calling any LoadAssetAsync — points to the directory containing .dat files
        public static string ConfigDirectory { get; set; } = "";

        public static AsyncOperationHandle<T> LoadAssetAsync<T>(string k) => LoadAssetAsync<T>((object)k);
        public static AsyncOperationHandle<T> LoadAssetAsync<T>(object k)
        {
            string key = k?.ToString() ?? "";
            object result = default(T);

            if (typeof(T) == typeof(TextAsset))
            {
                var path = Path.Combine(ConfigDirectory, key + ".dat");
                if (File.Exists(path))
                    result = new TextAsset(File.ReadAllBytes(path));
                else
                    result = new TextAsset();
            }

            return new AsyncOperationHandle<T>((T)result);
        }
        public static void Release<T>(T o) { } public static void Release<T>(AsyncOperationHandle<T> h) { }
        public static AsyncOperationHandle<IList<T>> LoadAssetsAsync<T>(object k, Action<T> c) => new AsyncOperationHandle<IList<T>>(default);
        public static AsyncOperationHandle<GameObject> InstantiateAsync(string k, Transform p = null) => new AsyncOperationHandle<GameObject>(default);
        // 4-arg overload the battle code uses to spawn character prefabs. Headless we have no
        // prefab to instantiate; return a completed handle with a null GameObject. Downstream
        // animator wiring on that null is handled by the null-receiver absorb (cosmetic only).
        public static AsyncOperationHandle<GameObject> InstantiateAsync(object k, Transform p = null, bool instantiateInWorldSpace = false, bool trackHandle = true) => new AsyncOperationHandle<GameObject>(default);
        // Resource-existence check (used by ProjectUtils.CheckResourceExist for optional skins/audio).
        // Headless we report "no locations" → the optional resource is treated as absent (cosmetic).
        public static AsyncOperationHandle<IList<UnityEngine.ResourceManagement.ResourceLocations.IResourceLocation>> LoadResourceLocationsAsync(object key, System.Type type)
            => new AsyncOperationHandle<IList<UnityEngine.ResourceManagement.ResourceLocations.IResourceLocation>>(new List<UnityEngine.ResourceManagement.ResourceLocations.IResourceLocation>());
    }
}
namespace UnityEngine.ResourceManagement.AsyncOperations
{
    public enum AsyncOperationStatus { None, Succeeded, Failed }
    public struct AsyncOperationHandle<T>
    {
        private T _result;
        public AsyncOperationHandle(T result) { _result = result; }
        public T Result => _result;
        public bool IsDone => true;
        public float PercentComplete => 1;
        public Task<T> Task => System.Threading.Tasks.Task.FromResult(_result);
        public T WaitForCompletion() => _result;
        public event Action<AsyncOperationHandle<T>> Completed { add { value(this); } remove { } }
    }
    public struct AsyncOperationHandle { public object Result => null; public bool IsDone => true; }
}
