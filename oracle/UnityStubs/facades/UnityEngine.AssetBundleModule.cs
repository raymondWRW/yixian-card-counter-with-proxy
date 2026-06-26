// UnityEngine.AssetBundleModule facade
using System;
namespace UnityEngine
{
    public class AssetBundle : Object
    {
        public static AssetBundle LoadFromFile(string path) => null;
        public static AssetBundle LoadFromMemory(byte[] binary) => null;
        public T LoadAsset<T>(string name) where T : Object => null;
        public Object[] LoadAllAssets() => new Object[0];
        public void Unload(bool unloadAllLoadedObjects) { }
    }
}
