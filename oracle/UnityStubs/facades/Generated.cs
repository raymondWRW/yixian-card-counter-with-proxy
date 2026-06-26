// AUTO-GENERATED facade stubs — do not edit by hand. Regenerate with `--gen-facades`.
// One empty stub per external type the game DLL references, with only the members it uses.
#pragma warning disable CS0626, CS0824, CS0649, CS0108, CS0660, CS0661
using System;
public class AddressableCache<T0>
{
}
public class AddressablesDefine
{
    public static string GetLocalCatalogHash(int a0) => default!;
}
public class AsyncLoadExtensions
{
    public static void LoadSprite(UnityEngine.UI.Image a0, string a1, string a2, bool a3, System.Threading.CancellationToken a4) { }
    public static Cysharp.Threading.Tasks.UniTask LoadSpriteAsync(UnityEngine.UI.Image a0, string a1, string a2, bool a3, System.Threading.CancellationToken a4) => default!;
}
public class BlockPanel
{
    public static void Active(float a0, bool a1, string a2) { }
    public static bool GetIsBlocking() => default!;
    public static bool GetIsShowing() => default!;
    public static void Deactive(float a0) { }
    public static void ActiveDelayFadeIn(float a0, float a1, string a2) { }
}
public class CollectionExtensions
{
}
public class CustomDialogueUGUI
{
    public void ClearCharacterBuffer() { }
    public UnityEngine.Transform characterContainer;
}
public class DebugPanel
{
}
public class DeveloperConfigManager
{
}
public class DialogueCharacterAnimItem
{
}
public class DialogueOnEndActionType
{
}
public struct FancyAlignment
{
}
public class FancySelectEvent
{
}
public class FileUtils
{
    public static void CheckDirectory(string a0) { }
}
public class GameGroupState
{
    public string owner;
    public bool isPrivate;
}
public class GameObjectExtensions
{
}
public class GamePlayer
{
    public string uid;
    public int status;
    public string customData;
    public bool isAI;
    public string username;
    public bool isJudge;
    public bool isOnline;
}
public class GameRoomState
{
    public string version;
    public Colyseus.Schema.ArraySchema<GamePlayer> judges;
}
public class GlobalDefine
{
    public static string apiUrl { get; }
    public static bool isOversea { get; }
    public static bool useReleasePreviewServer { get; set; }
    public static bool isSteamChina { get; }
    public static bool useLanServer { get; }
    public static bool useLocalServer { get; }
    public static bool useDevelopStableServer { get; }
    public int GAME_PLATFORM;
}
public class HandshakeFailedFixer
{
    public static void Fix() { }
}
public struct HashType
{
}
public class HashUtils
{
    public static string ComputeStringHash(string a0, HashType a1, bool a2) => default!;
}
public struct HintLevel
{
}
public class HintMessagePanel
{
    public static void Show(string a0, HintLevel a1) { }
}
public class HykbAntiListenerProxy
{
    public HykbAntiListenerProxy(System.Action<int, string> a0) { }
}
public class HYKBFcmListener
{
    public HYKBFcmListener() { }
}
public class HykbInitListenerProxy
{
    public HykbInitListenerProxy() { }
}
public class HykbUserExtraInfoListener
{
    public HykbUserExtraInfoListener() { }
    public com.m3839.sdk.login.bean.HykbUserExtInfo userExtraInfo { get; }
}
public class HykbUserListenerProxy
{
    public HykbUserListenerProxy(System.Action a0, System.Action a1, System.Action<int, string> a2) { }
    public com.m3839.sdk.login.bean.HykbUser user { get; }
}
public class ILRFancyCell
{
}
public class ILRFancyContext
{
    public System.Action<int> onCellClicked;
    public int selectedIndex;
}
public class ILRFancyGridCell
{
}
public class ILRFancyGridContext
{
    public int selectedIndex;
    public System.Action<int> onCellClicked;
}
public class ILRFancyGridView
{
    public void OnCellClicked(System.Action<int> a0) { }
    public void JumpTo(int a0, FancyAlignment a1) { }
    public void UpdateSelection(int a0) { }
    public void ScrollTo(int a0, float a1, EasingCore.Ease a2, FancyAlignment a3) { }
    public void JumpTo(float a0) { }
    public void RefreshItems() { }
    public int StartAxisCellCount { get; set; }
    public int SelectedIndex { get; }
    public float ScrollerPosition { get; }
}
public class ILRFancyRectContext
{
    public int selectedIndex;
    public System.Action<int> onCellClicked;
}
public class ILRFancyScrollRectCell
{
}
public class ILRFancyScrollRectView
{
    public void JumpTo(int a0, FancyAlignment a1) { }
    public void UpdateDatas(System.Collections.Generic.IList<ILRFancyDataBase> a0) { }
    public void OnCellClicked(System.Action<int> a0) { }
    public void UpdateSelection(int a0, bool a1) { }
    public void RefreshView() { }
    public void ScrollTo(int a0, float a1, EasingCore.Ease a2, FancyAlignment a3) { }
    public float GetSizeOfAllDatas() => default!;
    public float GetPageSize() => default!;
    public float Spacing { get; set; }
    public int SelectedIndex { get; }
    public float PaddingTop { get; }
    public float PaddingBottom { get; }
    public FancyScrollView.Scroller Scroller { get; }
    public float ScrollerPosition { get; }
}
public class ILRFancyScrollView
{
    public void UpdateDatas(System.Collections.Generic.IList<ILRFancyDataBase> a0) { }
    public void SelectCell(int a0) { }
    public FancySelectEvent onSelectionChanged;
}
public class ILRPanelBridge
{
}
public class ILRSubPanelBridge
{
}
public class L10NImage
{
    public UnityEngine.Sprite GetCurrentSprite() => default!;
}
public class LanServerDiscovery
{
    public static System.Threading.Tasks.Task<string> DiscoveryAsync(int a0, string a1) => default!;
}
public class LobbyClient
{
    public Cysharp.Threading.Tasks.UniTask<Response> ReconnectAsync() => default!;
    public event System.Action<wProtobuf.IMessage> OnMessageReceived { add { } remove { } }
    public Cysharp.Threading.Tasks.UniTask<Response> SendMessageAsync(wProtobuf.IMessage a0) => default!;
    public void SendMessage(wProtobuf.IMessage a0) { }
    public void Disconnect() { }
    public event System.Action OnConnected { add { } remove { } }
    public event System.Action OnDisconnected { add { } remove { } }
    public Cysharp.Threading.Tasks.UniTask<Response> ConnectAsync(string a0, string a1) => default!;
    public static LobbyClient main { get; }
    public bool isConnected { get; }
    public System.Func<wProtobuf.IMessage> userInfoProvider { get; set; }
    public Colyseus.ColyseusRoom<object> lobby { get; }
}
public class MessageBox
{
    public static MessageBoxWindow ShowWindow(string a0, string a1, System.Action a2, System.Action a3, MessageBoxType a4, MessageBoxWindowType a5) => default!;
    public static void HideAllWindows() { }
    public static MessageBox GetSafeInstance() => default!;
}
public class MessageBoxWindow
{
    public MessageBoxWindow SetType(MessageBoxType a0) => default!;
    public MessageBoxWindow SetButtonText(string a0, string a1) => default!;
    public void Hide() { }
    public MessageBoxWindow SetHideOnConfirm(bool a0) => default!;
}
public struct MessageBoxWindowType
{
}
public class NativeShare
{
    public NativeShare() { }
    public NativeShare AddFile(string a0, string a1) => default!;
    public NativeShare SetText(string a0) => default!;
    public void Share() { }
}
public class NetworkDateTimeOffset
{
    public static void CalibrateCurrentDateTime(long a0, float a1) { }
    public static System.DateTimeOffset Now { get; }
    public static long timestamp { get; }
    public static System.DateTimeOffset UtcNow { get; }
}
public struct NetworkState
{
}
public class NetworkStateChecker
{
    public static event System.Action OnConncet { add { } remove { } }
    public static NetworkState currentNetworkState { get; }
}
public class ObjectExtensions
{
    public static string GetDebugMessage(object a0, bool a1) => default!;
}
public class OpenURLOnClickTMPLink
{
}
public class PrefabSpawner
{
    public System.Collections.Generic.List<UnityEngine.GameObject> Spawn(int a0) => default!;
    public void DespawnAll() { }
}
public class PullToRefreshItem
{
    public UnityEngine.Events.UnityEvent onReachDistance { get; }
    public UnityEngine.Events.UnityEvent onRefreshBegin { get; }
    public UnityEngine.Events.UnityEvent onRefreshEnd { get; }
}
public class PullToRefreshScrollView
{
    public System.Collections.Generic.List<PullToRefreshItem> loadingItems { get; }
}
public class QRCodeUtils
{
    public static UnityEngine.Texture2D EncodeQrImage(string a0, int a1, int a2) => default!;
}
public class RailEventCallBackHandler
{
    public RailEventCallBackHandler(object a0, System.IntPtr a1) { }
}
public class RedDot
{
    public bool isShow { get; set; }
}
public class RoomStateBase
{
    public string customData;
    public Colyseus.Schema.ArraySchema<GamePlayer> players;
}
public class ScrollSnapPagination
{
    public void JumpToPage(int a0) { }
    public int pageCount { get; set; }
}
public class ShortcutManager
{
    public static void AddEscAction(System.Action a0, bool a1) { }
    public static void RemoveEscAction(System.Action a0) { }
    public static void RegisterAction(UnityEngine.KeyCode a0, System.Action a1, string a2) { }
    public static void UnregisterAction(UnityEngine.KeyCode a0) { }
    public static bool active { get; set; }
}
public struct SpineEmojiPlayMode
{
}
public class SpineEmojiRenderer
{
    public void SetData(string a0, SpineEmojiPlayMode a1) { }
    public void SetUIMaterial(UnityEngine.Material a0) { }
    public UnityEngine.Material uiDefaultMat { get; }
}
public class SpineExtensions
{
    public static UnityEngine.Vector3 GetWorldPositionGraphic(Spine.Bone a0, UnityEngine.Transform a1, float a2) => default!;
}
public class SpriteCache
{
    public static SpriteCache main { get; }
}
public class SystemUtils
{
    public static void OpenURLCompatible(string a0) { }
    public static void RequestStoreReview() { }
}
public class TapTapAchievementCallback
{
    public TapTapAchievementCallback() { }
}
public class TaskbarIconFlasher
{
    public static bool Flash() => default!;
}
public class TencentClsLogListener
{
    public static void AddExtraParam(string a0, string a1) { }
    public static void WriteLog(string a0, string a1, UnityEngine.LogType a2) { }
}
public class TMPInputFieldBytesLimit
{
    public static int GetStringLength(string a0) => default!;
    public void AddIllegalChars(System.Collections.Generic.List<System.Char> a0) { }
    public static int GetCharLength(System.Char a0) => default!;
}
public struct UILayer
{
}
public class UIPanelExtension
{
    public static void Show(UnityEngine.GameObject a0, DG.Tweening.TweenCallback a1, string a2) { }
    public static void Hide(UnityEngine.GameObject a0, DG.Tweening.TweenCallback a1, string a2) { }
}
public class UISubPanelBase
{
    public void Show() { }
    public void Hide() { }
    public bool isShow { get; }
    public bool useAnimation;
}
public class UnityPointerEvent
{
}
public class UserSessionData
{
    public string roomId;
    public string groupId;
}
public class WordsFilterUtil
{
    public static bool IllegalWordsExsit(string a0) => default!;
    public static string Filter(string a0, string a1) => default!;
    public static Cysharp.Threading.Tasks.UniTask LoadAsync() => default!;
}
public class XXTEA
{
    public static string EncryptToBase64String(string a0, string a1) => default!;
}
namespace AppleAuth
{
    public class AppleAuthManager
    {
        public AppleAuthManager(AppleAuth.Interfaces.IPayloadDeserializer a0) { }
        public void Update() { }
        public void GetCredentialState(string a0, System.Action<AppleAuth.Enums.CredentialState> a1, System.Action<AppleAuth.Interfaces.IAppleError> a2) { }
        public void QuickLogin(System.Action<AppleAuth.Interfaces.ICredential> a0, System.Action<AppleAuth.Interfaces.IAppleError> a1) { }
        public void LoginWithAppleId(AppleAuth.Enums.LoginOptions a0, System.Action<AppleAuth.Interfaces.ICredential> a1, System.Action<AppleAuth.Interfaces.IAppleError> a2) { }
    }
}
namespace AppleAuth.Enums
{
    public struct CredentialState
    {
    }
    public struct LoginOptions
    {
    }
}
namespace AppleAuth.Interfaces
{
    public class IAppleError
    {
        public string LocalizedDescription { get; }
    }
    public class IAppleIDCredential
    {
        public byte[] IdentityToken { get; }
    }
    public class ICredential
    {
        public string User { get; }
    }
    public class IPayloadDeserializer
    {
    }
}
namespace AppleAuth.Native
{
    public class PayloadDeserializer
    {
        public PayloadDeserializer() { }
    }
}
namespace Cinemachine
{
    public struct CinemachineBlendDefinition
    {
        public struct Style
        {
        }
        public Cinemachine.CinemachineBlendDefinition.Style m_Style;
    }
    public class CinemachineTargetGroup
    {
        public struct Target
        {
            public UnityEngine.Transform target;
        }
        public Cinemachine.CinemachineTargetGroup.Target[] m_Targets;
    }
    public class ICinemachineCamera
    {
    }
    public struct LensSettings
    {
        public float NearClipPlane;
        public float FarClipPlane;
        public float OrthographicSize;
    }
}
namespace Coffee.UIExtensions
{
    public class UIParticle
    {
    }
}
namespace Colyseus
{
    public class ColyseusConnection
    {
        public string lastCloseError { get; }
        public NativeWebSocket.WebSocketState State { get; }
    }
    public class ColyseusRoom<T0>
    {
    }
}
namespace Colyseus.Schema
{
    public class ArraySchema<T0>
    {
    }
}
namespace com.m3839.sdk
{
    public class HykbContext
    {
        public int SCREEN_LANDSCAPE;
    }
}
namespace com.m3839.sdk.achievement
{
    public class HykbAchievement
    {
        public static void releaseSDK() { }
    }
}
namespace com.m3839.sdk.login
{
    public class HykbLogin
    {
        public static void SetUserListener(com.m3839.sdk.login.listener.HykbUserListener a0) { }
        public static void SetAntiListener(com.m3839.sdk.login.listener.HykbAntiListener a0) { }
        public static void Init(string a0, int a1, com.m3839.sdk.login.listener.HykbV2InitListener a2) { }
        public static com.m3839.sdk.login.bean.HykbUser GetUser() => default!;
        public static void loadUserExtInfo(com.m3839.sdk.login.listener.HykbUserExtInfoListener a0) { }
        public static void Logout() { }
        public static void Login() { }
    }
}
namespace com.m3839.sdk.login.bean
{
    public class HykbUser
    {
        public string getNick() => default!;
        public string toString() => default!;
        public string getUserId() => default!;
        public string getAccessToken() => default!;
    }
    public class HykbUserExtInfo
    {
        public int getAgeStage() => default!;
    }
}
namespace com.m3839.sdk.login.listener
{
    public class HykbAntiListener
    {
    }
    public class HykbUserExtInfoListener
    {
    }
    public class HykbUserListener
    {
    }
    public class HykbV2InitListener
    {
    }
}
namespace com.m3839.sdk.pay
{
    public class HykbPay
    {
        public static void ReleaseSDK() { }
    }
}
namespace com.m3839.sdk.single
{
    public class UnionFcmSDK
    {
        public static void Init(string a0, int a1, com.m3839.sdk.single.UnionV2FcmListener a2) { }
    }
    public class UnionV2FcmListener
    {
    }
}
namespace Cysharp.Threading.Tasks
{
    public struct DelayType
    {
    }
    public class EnumeratorAsyncExtensions
    {
        public static Cysharp.Threading.Tasks.UniTask ToUniTask(System.Collections.IEnumerator a0, Cysharp.Threading.Tasks.PlayerLoopTiming a1, System.Threading.CancellationToken a2) => default!;
    }
    public class UnityAsyncExtensions
    {
        public struct UnityWebRequestAsyncOperationAwaiter
        {
            public UnityEngine.Networking.UnityWebRequest GetResult() => default!;
            public bool IsCompleted { get; }
        }
        public static Cysharp.Threading.Tasks.UnityAsyncExtensions.UnityWebRequestAsyncOperationAwaiter GetAwaiter(UnityEngine.Networking.UnityWebRequestAsyncOperation a0) => default!;
    }
}
namespace DarkSun.Login
{
    public class DarkSunLogin
    {
        public static void Init(string a0, string a1, string a2) { }
        public static void DeleteLocalUser() { }
        public static Cysharp.Threading.Tasks.UniTask<DarkSun.Login.DarkSunUser> GetLocalUserAsync() => default!;
        public static Cysharp.Threading.Tasks.UniTask<DarkSun.Login.JsonResponse<DarkSun.Login.DarkSunUser>> LoginAsync(string a0, string a1, bool a2) => default!;
        public static Cysharp.Threading.Tasks.UniTask<DarkSun.Login.SimpleResponse> RequestCaptchaAsync(string a0, string a1, string a2) => default!;
        public static Cysharp.Threading.Tasks.UniTask<DarkSun.Login.JsonResponse<DarkSun.Login.DarkSunUser>> RegisterAsync(string a0, string a1, string a2) => default!;
        public static Cysharp.Threading.Tasks.UniTask<DarkSun.Login.SimpleResponse> ModifyPassword(string a0, string a1, string a2) => default!;
        public static string appId { get; }
    }
}
namespace DarkSun.Pay
{
    public class DarkSunPay
    {
        public static Cysharp.Threading.Tasks.UniTask<DarkSun.Login.SimpleResponse> StartPay(System.Collections.Generic.Dictionary<string, string> a0) => default!;
    }
}
namespace DarkTonic.MasterAudio
{
    public class MasterAudioGroup
    {
    }
    public class MusicSetting
    {
        public string alias;
        public string songName;
    }
    public class PlaySoundResult
    {
    }
}
namespace DG.Tweening
{
    public class DOTweenModuleSprite
    {
        public static DG.Tweening.Core.TweenerCore<UnityEngine.Color, UnityEngine.Color, DG.Tweening.Plugins.Options.ColorOptions> DOFade(UnityEngine.SpriteRenderer a0, float a1, float a2) => default!;
    }
    public struct PathMode
    {
    }
    public struct PathType
    {
    }
    public class TweenExtensions
    {
        public static void Kill(DG.Tweening.Tween a0, bool a1) { }
        public static bool IsPlaying(DG.Tweening.Tween a0) => default!;
        public static void Goto(DG.Tweening.Tween a0, float a1, bool a2) { }
        public static void PlayForward(DG.Tweening.Tween a0) { }
    }
}
namespace DG.Tweening.Plugins.Core.PathCore
{
    public class Path
    {
    }
}
namespace DG.Tweening.Plugins.Options
{
    public struct NoOptions
    {
    }
    public struct PathOptions
    {
    }
    public struct QuaternionOptions
    {
    }
}
namespace EasingCore
{
    public struct Ease
    {
    }
}
namespace FancyScrollView
{
    public class FancyCell<T0, T1>
    {
    }
    public class FancyGridView<T0, T1>
    {
    }
    public struct ScrollDirection
    {
    }
    public class Scroller
    {
        public void ScrollTo(float a0, float a1, EasingCore.Ease a2, System.Action a3) { }
        public bool Draggable { get; set; }
        public FancyScrollView.ScrollDirection ScrollDirection { get; }
        public int totalCount { get; }
        public float Position { get; set; }
        public UnityEngine.UI.Scrollbar Scrollbar { get; }
    }
}
namespace FunkyCode
{
    public class LightingManager2D
    {
        public static FunkyCode.LightingManager2D Get() => default!;
        public FunkyCode.LightingSettings.Profile profile;
    }
}
namespace FunkyCode.LightingSettings
{
    public class Profile
    {
        public UnityEngine.Color DarknessColor { get; set; }
    }
}
namespace I2.Loc
{
    public class TermData
    {
    }
}
namespace IngameDebugConsole
{
    public class ConsoleMethodInfo
    {
        public string command;
        public string signature;
    }
    public class DebugLogConsole
    {
        public static void FindCommands(string a0, bool a1, System.Collections.Generic.List<IngameDebugConsole.ConsoleMethodInfo> a2) { }
        public static void ExecuteCommand(string a0) { }
        public static void AddCommand(string a0, string a1, System.Action a2) { }
        public static void RemoveCommand(string a0) { }
    }
}
namespace LeanCloud.Storage
{
    public class LCObject
    {
        public object Item { get; }
        public string ObjectId { get; }
    }
}
namespace LitJson
{
    public class JsonMapper
    {
        public static string ToJson(object a0) => default!;
        public static object ToObject(string a0, System.Type a1) => default!;
    }
}
namespace NativeWebSocket
{
    public struct WebSocketState
    {
    }
}
namespace NodeCanvas.DialogueTrees
{
    public class DialogueActor
    {
        public string name { get; set; }
    }
    public class DialogueTree
    {
        public class ActorParameter
        {
            public ActorParameter(string a0, NodeCanvas.DialogueTrees.IDialogueActor a1) { }
            public NodeCanvas.DialogueTrees.IDialogueActor actor { get; }
        }
        public System.Collections.Generic.List<NodeCanvas.DialogueTrees.DialogueTree.ActorParameter> actorParameters;
    }
    public class DialogueTreeController
    {
        public void StartDialogue() { }
    }
    public class DTNode
    {
        public string actorName { get; set; }
    }
    public class IDialogueActor
    {
        public string name { get; }
    }
    public class Statement
    {
        public Statement(string a0) { }
        public string meta { get; set; }
    }
    public class StatementNode
    {
        public NodeCanvas.DialogueTrees.Statement statement;
    }
}
namespace NodeCanvas.Framework
{
    public class Blackboard
    {
    }
    public class Connection
    {
    }
    public class Graph
    {
        public event System.Action<bool> onFinish { add { } remove { } }
        public void Stop(bool a0) { }
        public NodeCanvas.Framework.Connection ConnectNodes(NodeCanvas.Framework.Node a0, NodeCanvas.Framework.Node a1, int a2, int a3) => default!;
        public bool SelfSerialize() => default!;
        public string GetSerializedJsonData() => default!;
        public System.Collections.Generic.List<UnityEngine.Object> GetSerializedReferencesData() => default!;
        public NodeCanvas.Framework.Internal.GraphSource GetGraphSourceMetaDataCopy() => default!;
        public System.Collections.Generic.List<NodeCanvas.Framework.Node> allNodes { get; }
    }
    public class GraphOwner
    {
        public struct DisableAction
        {
        }
        public struct EnableAction
        {
        }
        public NodeCanvas.Framework.IBlackboard blackboard { get; set; }
        public NodeCanvas.Framework.GraphOwner.EnableAction enableAction { get; set; }
        public NodeCanvas.Framework.GraphOwner.DisableAction disableAction { get; set; }
        public string boundGraphSerialization { get; set; }
        public System.Collections.Generic.List<UnityEngine.Object> boundGraphObjectReferences { get; set; }
        public NodeCanvas.Framework.Internal.GraphSource boundGraphSource { get; set; }
    }
    public class GraphOwner<T0>
    {
    }
    public class IBlackboard
    {
    }
    public class Node
    {
    }
}
namespace NodeCanvas.Framework.Internal
{
    public class GraphSource
    {
    }
}
namespace Plugins.AntiAddictionUIKit
{
    public class CheckPayResult
    {
        public int status;
        public string description;
    }
}
namespace rail
{
    public struct EnumRailDirtyWordsType
    {
    }
    public class IRailAchievementHelper
    {
        public rail.IRailPlayerAchievement CreatePlayerAchievement(rail.RailID a0) => default!;
    }
    public class IRailInGameStorePurchaseHelper
    {
        public rail.RailResult AsyncShowPaymentWindow(string a0, string a1) => default!;
    }
    public class IRailPlayerAchievement
    {
        public rail.RailResult HasAchieved(string a0, ref bool a1) => default!;
        public rail.RailResult MakeAchievement(string a0) => default!;
        public rail.RailResult AsyncStoreAchievement(string a0) => default!;
        public rail.RailResult AsyncRequestAchievement(string a0) => default!;
    }
    public class rail_api
    {
        public static rail.IRailFactory RailFactory() => default!;
    }
    public class RailCallBackHelper
    {
        public void RegisterCallback(rail.RAILEventID a0, RailEventCallBackHandler a1) { }
        public void UnregisterCallback(rail.RAILEventID a0, RailEventCallBackHandler a1) { }
        public static rail.RailCallBackHelper Instance { get; }
    }
    public class RailInGameStorePurchaseResult
    {
    }
    public class RailSessionTicket
    {
        public string ticket;
    }
}
namespace SimpleFileBrowser
{
    public class FileBrowser
    {
        public struct PickMode
        {
        }
        public static System.Collections.IEnumerator WaitForSaveDialog(SimpleFileBrowser.FileBrowser.PickMode a0, bool a1, string a2, string a3, string a4, string a5) => default!;
        public static System.Collections.IEnumerator WaitForLoadDialog(SimpleFileBrowser.FileBrowser.PickMode a0, bool a1, string a2, string a3, string a4, string a5) => default!;
        public static bool Success { get; }
        public static string[] Result { get; }
    }
}
namespace Spine
{
    public class PathAttachment
    {
    }
    public class PathConstraint
    {
        public float MixRotate { get; set; }
        public float MixY { get; set; }
        public float MixX { get; set; }
    }
}
namespace Spine.Unity
{
    public class BoneFollowerGraphic
    {
    }
}
namespace Spine.Unity.AttachmentTools
{
    public class AttachmentCloneExtensions
    {
        public static Spine.Attachment GetRemappedClone(Spine.Attachment a0, UnityEngine.Sprite a1, UnityEngine.Material a2, bool a3, bool a4, bool a5, bool a6, bool a7, UnityEngine.TextureFormat a8, bool a9) => default!;
    }
}
namespace Steamworks
{
    public struct AppId
    {
        public static uint op_Implicit(Steamworks.AppId a0) => default!;
    }
    public struct SteamId
    {
    }
    public class SteamUtils
    {
        public static bool IsOverlayEnabled { get; }
    }
}
namespace Steamworks.Data
{
    public class Achievement
    {
        public Achievement(string a0) { }
        public bool Trigger(bool a0) => default!;
        public bool State { get; }
    }
}
namespace TapTap.Achievement
{
    public class IAchievementCallback
    {
    }
}
namespace TapTap.AntiAddiction
{
    public class AntiAddictionUIKit
    {
        public static void StartupWithTapTap(string a0) { }
        public static void Startup(string a0, bool a1) { }
        public static void SubmitPayResult(long a0, System.Action a1, System.Action<string> a2) { }
        public static void Exit() { }
        public static void Init(TapTap.AntiAddiction.Model.AntiAddictionConfig a0, System.Action<int, string> a1) { }
        public static void CheckPayLimit(long a0, System.Action<Plugins.AntiAddictionUIKit.CheckPayResult> a1, System.Action<string> a2) { }
    }
}
namespace TapTap.AntiAddiction.Model
{
    public class AntiAddictionConfig
    {
        public AntiAddictionConfig() { }
        public string gameId;
        public bool showSwitchAccount;
    }
}
namespace TapTap.Common
{
    public struct RegionType
    {
    }
    public class TapConfig
    {
        public class Builder
        {
            public Builder() { }
            public TapTap.Common.TapConfig.Builder ClientID(string a0) => default!;
            public TapTap.Common.TapConfig.Builder ClientToken(string a0) => default!;
            public TapTap.Common.TapConfig.Builder ServerURL(string a0) => default!;
            public TapTap.Common.TapConfig.Builder RegionType(TapTap.Common.RegionType a0) => default!;
            public TapTap.Common.TapConfig ConfigBuilder() => default!;
        }
    }
    public class TapConfigBuilderForPayment
    {
        public static TapTap.Common.TapConfig.Builder TapPaymentConfig(TapTap.Common.TapConfig.Builder a0, string a1, string a2, string a3) => default!;
    }
    public class TapConfigBuilderForTapDB
    {
        public static TapTap.Common.TapConfig.Builder TapDBConfig(TapTap.Common.TapConfig.Builder a0, bool a1, string a2, string a3, bool a4, System.Collections.Generic.Dictionary<string, object> a5) => default!;
    }
    public class TapError
    {
        public string errorDescription;
    }
}
namespace TapTap.Payment
{
    public class SkuDetails
    {
        public string goodsOpenId;
    }
    public class TapPayment
    {
        public static void QueryProducts(string[] a0, System.Action<System.Collections.Generic.List<TapTap.Payment.SkuDetails>, TapTap.Common.TapError> a1) { }
        public static void LaunchBillingFlow(TapTap.Payment.SkuDetails a0, string a1, string a2, string a3, System.Action<int, TapTap.Common.TapError> a4) { }
    }
}
namespace TapTap.TapDB
{
    public class TapDB
    {
        public static void Init(string a0, string a1, string a2, bool a3) { }
        public static void SetUser(string a0) { }
        public static void SetServer(string a0) { }
        public static void UserInitialize(string a0) { }
        public static void UserUpdate(string a0) { }
        public static void TrackEvent(string a0, string a1) { }
        public static void SetName(string a0) { }
        public static void ClearUser() { }
    }
}
namespace TapTap.Update
{
    public class TapUpdate
    {
        public static void UpdateGame(System.Action a0) { }
    }
}
namespace TMPro
{
    public struct AtlasPopulationMode
    {
    }
    public struct HorizontalAlignmentOptions
    {
    }
    public struct TMP_CharacterInfo
    {
        public int materialReferenceIndex;
        public int vertexIndex;
        public TMPro.TMP_TextElementType elementType;
        public int spriteIndex;
        public bool isVisible;
        public TMPro.TMP_Vertex vertex_BL;
        public TMPro.TMP_Vertex vertex_TL;
        public TMPro.TMP_Vertex vertex_TR;
        public TMPro.TMP_Vertex vertex_BR;
    }
    public struct TMP_LinkInfo
    {
        public string GetLinkID() => default!;
    }
    public struct TMP_MeshInfo
    {
        public void Clear() { }
        public UnityEngine.Vector3[] vertices;
    }
    public class TMP_SpriteGlyph
    {
        public UnityEngine.Sprite sprite;
    }
    public struct TMP_TextElementType
    {
    }
    public class TMP_TextInfo
    {
        public TMPro.TMP_LinkInfo[] linkInfo;
        public TMPro.TMP_MeshInfo[] meshInfo;
        public int materialCount;
        public TMPro.TMP_CharacterInfo[] characterInfo;
        public int characterCount;
    }
    public class TMP_TextUtilities
    {
        public static int FindIntersectingLink(TMPro.TMP_Text a0, UnityEngine.Vector3 a1, UnityEngine.Camera a2) => default!;
    }
    public struct TMP_Vertex
    {
        public UnityEngine.Vector3 position;
    }
    public struct TMP_VertexDataUpdateFlags
    {
    }
}
namespace UniRx
{
    public class BehaviorSubject<T0>
    {
    }
    public class DisposableExtensions
    {
    }
    public struct FrameCountType
    {
    }
    public class IScheduler
    {
    }
    public class ObserveExtensions
    {
    }
    public class Scheduler
    {
        public static UniRx.IScheduler MainThreadIgnoreTimeScale { get; }
    }
    public struct Unit
    {
    }
}
namespace UniRx.Triggers
{
    public class ObservablePointerClickTrigger
    {
    }
    public class ObservableTriggerExtensions
    {
        public static System.IObservable<UnityEngine.EventSystems.PointerEventData> OnBeginDragAsObservable(UnityEngine.EventSystems.UIBehaviour a0) => default!;
        public static System.IObservable<UnityEngine.EventSystems.PointerEventData> OnDragAsObservable(UnityEngine.EventSystems.UIBehaviour a0) => default!;
        public static System.IObservable<UnityEngine.EventSystems.PointerEventData> OnEndDragAsObservable(UnityEngine.EventSystems.UIBehaviour a0) => default!;
        public static System.IObservable<UnityEngine.EventSystems.PointerEventData> OnPointerClickAsObservable(UnityEngine.EventSystems.UIBehaviour a0) => default!;
        public static System.IObservable<UnityEngine.EventSystems.PointerEventData> OnScrollAsObservable(UnityEngine.EventSystems.UIBehaviour a0) => default!;
        public static System.IObservable<UnityEngine.EventSystems.PointerEventData> OnPointerEnterAsObservable(UnityEngine.EventSystems.UIBehaviour a0) => default!;
        public static System.IObservable<UnityEngine.EventSystems.PointerEventData> OnPointerExitAsObservable(UnityEngine.EventSystems.UIBehaviour a0) => default!;
        public static System.IObservable<UnityEngine.EventSystems.PointerEventData> OnPointerDownAsObservable(UnityEngine.EventSystems.UIBehaviour a0) => default!;
        public static System.IObservable<UnityEngine.EventSystems.PointerEventData> OnPointerUpAsObservable(UnityEngine.EventSystems.UIBehaviour a0) => default!;
        public static System.IObservable<UnityEngine.EventSystems.PointerEventData> OnInitializePotentialDragAsObservable(UnityEngine.EventSystems.UIBehaviour a0) => default!;
        public static System.IObservable<UnityEngine.EventSystems.PointerEventData> OnDropAsObservable(UnityEngine.EventSystems.UIBehaviour a0) => default!;
    }
}
namespace UnityEngine
{
    public class ColorUtility
    {
        public static bool TryParseHtmlString(string a0, ref UnityEngine.Color a1) => default!;
        public static string ToHtmlStringRGBA(UnityEngine.Color a0) => default!;
        public static string ToHtmlStringRGB(UnityEngine.Color a0) => default!;
    }
    public class Graphics
    {
        public static void Blit(UnityEngine.Texture a0, UnityEngine.RenderTexture a1) { }
    }
    public class GUIUtility
    {
        public static string systemCopyBuffer { get; set; }
    }
    public class ImageConversion
    {
        public static byte[] EncodeToPNG(UnityEngine.Texture2D a0) => default!;
        public static byte[] EncodeToJPG(UnityEngine.Texture2D a0) => default!;
    }
    public struct LogType
    {
    }
    public struct Matrix4x4
    {
        public UnityEngine.Vector3 MultiplyPoint3x4(UnityEngine.Vector3 a0) => default!;
    }
    public class Ping
    {
        public Ping(string a0) { }
        public void DestroyPing() { }
        public bool isDone { get; }
        public int time { get; }
    }
    public class QualitySettings
    {
        public static void SetQualityLevel(int a0) { }
        public static int vSyncCount { get; set; }
    }
    public class RectTransformUtility
    {
        public static bool RectangleContainsScreenPoint(UnityEngine.RectTransform a0, UnityEngine.Vector2 a1, UnityEngine.Camera a2) => default!;
        public static bool ScreenPointToLocalPointInRectangle(UnityEngine.RectTransform a0, UnityEngine.Vector2 a1, UnityEngine.Camera a2, ref UnityEngine.Vector2 a3) => default!;
        public static bool ScreenPointToWorldPointInRectangle(UnityEngine.RectTransform a0, UnityEngine.Vector2 a1, UnityEngine.Camera a2, ref UnityEngine.Vector3 a3) => default!;
        public static UnityEngine.Vector2 WorldToScreenPoint(UnityEngine.Camera a0, UnityEngine.Vector3 a1) => default!;
    }
    public class SystemInfo
    {
        public static string deviceUniqueIdentifier { get; }
        public static int maxTextureSize { get; }
    }
    public struct TextureFormat
    {
    }
    public struct Touch
    {
        public UnityEngine.TouchPhase phase { get; }
        public UnityEngine.Vector2 position { get; }
    }
    public struct TouchPhase
    {
    }
    public class TrailRenderer
    {
        public bool emitting { get; set; }
    }
}
namespace UnityEngine.Animations
{
    public struct ConstraintSource
    {
        public UnityEngine.Transform sourceTransform { get; set; }
        public float weight { get; set; }
    }
    public class PositionConstraint
    {
        public int AddSource(UnityEngine.Animations.ConstraintSource a0) => default!;
    }
}
namespace UnityEngine.Events
{
    public class UnityEventBase
    {
        public void RemoveAllListeners() { }
    }
}
namespace UnityEngine.Networking
{
    public class UploadHandler
    {
    }
    public class UploadHandlerRaw
    {
        public UploadHandlerRaw(byte[] a0) { }
    }
}
namespace UnityEngine.Purchasing
{
    public class IAppleConfiguration
    {
        public void SetApplePromotionalPurchaseInterceptorCallback(System.Action<UnityEngine.Purchasing.Product> a0) { }
        public bool canMakePayments { get; }
    }
    public class IAppleExtensions
    {
        public void RegisterPurchaseDeferredListener(System.Action<UnityEngine.Purchasing.Product> a0) { }
        public string GetTransactionReceiptForProduct(UnityEngine.Purchasing.Product a0) => default!;
    }
}
namespace UnityEngine.Purchasing.Extension
{
    public class IPurchasingModule
    {
    }
    public class PurchaseFailureDescription
    {
        public UnityEngine.Purchasing.PurchaseFailureReason reason { get; }
        public string message { get; }
    }
}
namespace UnityEngine.SceneManagement
{
    public struct LoadSceneMode
    {
    }
}
namespace UnityEngine.TextCore
{
    public class Glyph
    {
        public uint index { get; }
    }
}
namespace UnityEngine.TextCore.LowLevel
{
    public struct GlyphRenderMode
    {
    }
}
namespace UnityEngine.UI
{
    public class HorizontalOrVerticalLayoutGroup
    {
        public float spacing { get; }
    }
    public struct SpriteState
    {
        public UnityEngine.Sprite highlightedSprite { get; set; }
        public UnityEngine.Sprite pressedSprite { get; set; }
        public UnityEngine.Sprite selectedSprite { get; set; }
        public UnityEngine.Sprite disabledSprite { get; set; }
    }
}
namespace UnityEngine.UI.Extensions
{
    public class HorizontalScrollSnap
    {
        public void AddChild(UnityEngine.GameObject a0) { }
        public void UpdateLayout() { }
    }
    public class ScrollSnapBase
    {
        public class SelectionPageChangedEvent
        {
        }
        public UnityEngine.UI.Extensions.ScrollSnapBase.SelectionPageChangedEvent OnSelectionPageChangedEvent { get; }
    }
    public class UIFlippable
    {
        public bool horizontal { get; set; }
    }
    public class UILineRenderer
    {
        public float LineThickness { get; set; }
        public UnityEngine.Vector2[] Points { get; set; }
    }
}
namespace UnityEngine.Video
{
    public class VideoPlayer
    {
        public void Play() { }
        public double length { get; }
    }
}
#pragma warning restore CS0626, CS0824, CS0649, CS0108, CS0660, CS0661
