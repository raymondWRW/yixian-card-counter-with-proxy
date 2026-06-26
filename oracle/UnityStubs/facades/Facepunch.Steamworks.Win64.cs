// Facepunch.Steamworks facade
namespace Steamworks
{
    public static class SteamClient { public static bool IsValid => false; public static void Init(uint appid) { } public static void Shutdown() { } public static void RunCallbacks() { } public static ulong SteamId => 0; public static string Name => ""; }
    public static class SteamUser { public static bool BLoggedOn() => false; }
    public static class SteamUserStats { public static bool RequestCurrentStats() => false; public static bool SetAchievement(string n) => false; public static bool StoreStats() => false; }
    public static class SteamApps { public static string GameLanguage => "english"; }
    public static class SteamFriends { public static string PersonaName => ""; }
    public struct AuthTicket : System.IDisposable { public byte[] Data => new byte[0]; public void Dispose() { } }
}
