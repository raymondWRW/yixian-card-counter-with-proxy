// RailSDK facade
using System;
namespace rail
{
    public static class RailFactory { public static IRailFactory RailFactory_() => null; }
    public interface IRailFactory { IRailPlayer RailPlayer(); IRailUtils RailUtils(); IRailInGamePurchase RailInGamePurchase(); }
    public interface IRailPlayer { RailID GetRailID(); }
    public interface IRailUtils { string GetLaunchAppParameters(); }
    public interface IRailInGamePurchase { }
    public struct RailID { public ulong id_; public RailID(ulong id) { id_ = id; } }
    public enum RailResult { kSuccess = 0, kFailure = 1 }
    public static class RailEventDispatcher { public static void Register<T>(Action<T> h) { } public static void Unregister<T>(Action<T> h) { } }
    public class EventBase { public RailResult result; }
    public class PlayerAchievementReceived : EventBase { }
    public class AcquireSessionTicketResponse : EventBase { public string session_ticket; }
    public class RailInGameStorePurchasePayWindowDisplayed : EventBase { }
    public enum RAILEventID { cycledefine_cycleMin = 0, cycledefine_cycleMax = 10000 }
    public class RailInGameStorePurchasePayWindowClosed : EventBase { }
    // Profanity-filter result for username display — cosmetic; headless we report "clean".
    public class RailDirtyWordsCheckResult : EventBase { public string check_result_text; public int dirty_type; }
}
