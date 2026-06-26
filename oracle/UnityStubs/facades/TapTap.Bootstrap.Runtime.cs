// TapTap.Bootstrap.Runtime facade
namespace TapTap.Bootstrap
{
    public static class TapBootstrap { public static void Init(TapConfig c) { } }
    public class TapConfig { public string ClientID { get; set; } public string ClientToken { get; set; } public string ServerURL { get; set; } public TapConfig(string i, string t, string u) { ClientID = i; ClientToken = t; ServerURL = u; } }
    public class TDSUser { public string objectId { get; set; } public string name { get; set; } }
}
