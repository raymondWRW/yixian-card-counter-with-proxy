// TapTap.Login facade
using System.Threading.Tasks;
namespace TapTap.Login
{
    public static class TapLogin { public static void Init(string id) { } public static Task<AccessToken> Login() => Task.FromResult<AccessToken>(null); public static void Logout() { } public static Task<AccessToken> GetAccessToken() => Task.FromResult<AccessToken>(null); }
    public class AccessToken { public string kid { get; set; } public string token_type { get; set; } public string mac_key { get; set; } public string mac_algorithm { get; set; } }
}
