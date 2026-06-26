// GameClient facade — the game's network client (global namespace, external CLR type).
// Headless replay never performs networking; this stub only needs to exist so types that
// hold a GameClient field (e.g. BattleManager.m_Client) can be instantiated.
using System;
using System.Collections.Generic;

public class GameClient
{
    public string uid => "";
    public string username { get; set; } = "";
    public bool isInRoom => false;
    public bool isGroupOwner => false;
    public object group => null;
    public string blockCreatingOperationReason => "";
    // Network events: some managers subscribe to these during init; headless they never fire.
    public event Action<wProtobuf.IMessage> OnRoomMessageReceived { add { } remove { } }
    public event Action<wProtobuf.IMessage> OnGroupMessageReceived { add { } remove { } }
    public event Action<string> OnPlayerJoinRoom { add { } remove { } }
    public event Action<string> OnPlayerLeaveRoom { add { } remove { } }
    // Network methods are never called in headless combat — left unimplemented intentionally.
}
