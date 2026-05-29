"""
addon.py (trimmed)
──────────────────
mitmproxy addon for the card counter. Decodes darksungame.com WebSocket
frames, mutates the client-side shadow on each gameplay message, and pushes
parsed GameState objects onto state_queue for the UI consumer thread.

Stripped from the original AI-bot addon: no game_loop, action_executor,
LLM, or traffic-file logging. Just decode → shadow → state_queue.

Imported as a top-level module (proxy/ is on sys.path) so the internal
`import shadow_state` calls in the ported modules resolve to the same
singleton instances this file uses.
"""
import copy
import datetime
import json
import os
import threading
from pathlib import Path

from mitmproxy import ctx

from decoder import decode_frame
from game_state import parse_game_state, CardState, card_name
from state_queue import state_queue, new_game_event, round_ended_event
import shadow_state

TARGET_HOST = "darksungame.com"
CONFIG_FILE = str(Path(__file__).resolve().parent / "config.json")

# ─── User UID (detected from /auth/login or GameStatus pb["6"]) ───────────────
_me_uid_lock = threading.Lock()
_me_uid: str = ""

# Last resolved battle pairing (winner/loser UIDs) — used later for matchup.
last_battle: dict = {}
# UID of the opponent the user most recently fought (BattleResult involving me).
my_last_opponent: str = ""

# Reroll events for the deck counter, drained by proxy_view.Counter. Each entry
# is {"old": <discarded card name>, "new": <drawn card name>}.
reroll_events: list = []

# Fate ids the user has chosen this game (breakthrough rewards), in pick order.
chosen_fates: list = []


def _load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_me_uid() -> str:
    with _me_uid_lock:
        return _me_uid


def _set_me_uid(uid: str):
    global _me_uid
    with _me_uid_lock:
        if uid and uid != _me_uid:
            _me_uid = uid
            cfg = _load_config()
            cfg["user_uid"] = uid
            _save_config(cfg)
            _log(f"[uid] user UID detected: {uid}")


_me_uid = _load_config().get("user_uid", "")


def _log(msg: str):
    try:
        ctx.log.info(msg)
    except Exception:
        print(msg)


# ─── blackboxprotobuf typedefs (force packed-varint fields to bytes) ──────────
_GAMESTATUS_TYPEDEF = {
    "5": {"type": "message", "message_typedef": {
        "200": {"type": "message", "message_typedef": {
            "6": {"type": "bytes"},
            "7": {"type": "bytes"},
        }},
    }},
    "6": {"type": "message", "message_typedef": {
        "1": {"type": "bytes"},
        "2": {"type": "bytes"},
        "200": {"type": "bytes"},
    }},
}
_PLAYERDATA_TYPEDEF = {
    "1": {"type": "message", "message_typedef": {
        "200": {"type": "message", "message_typedef": {
            "6": {"type": "bytes"},
            "7": {"type": "bytes"},
        }},
    }},
    "2": {"type": "message", "message_typedef": {
        "1": {"type": "bytes"},
        "2": {"type": "bytes"},
        "200": {"type": "bytes"},
    }},
}
_PENDINGTALENT_TYPEDEF = {"1": {"type": "bytes"}}


def _decode_pb(b64, typedef=None) -> dict:
    import base64
    import blackboxprotobuf
    try:
        raw = base64.b64decode(b64)
        if typedef:
            return blackboxprotobuf.decode_message(raw, typedef)[0]
        return blackboxprotobuf.decode_message(raw)[0]
    except Exception:
        return {}


# ─── msgpack-type predicates ──────────────────────────────────────────────────
def _inner(mp):
    if not isinstance(mp, list) or len(mp) < 2:
        return None
    return mp[1] if isinstance(mp[1], dict) else None


def _is_start_game_resp(mp) -> bool:
    inner = _inner(mp)
    return bool(inner and inner.get("type") == "StartGameResp")


def _is_round_end(mp) -> bool:
    inner = _inner(mp)
    return bool(inner and inner.get("type") == "BattleResult")


# ─── Shadow / state-queue plumbing ────────────────────────────────────────────
_last_my_state_lock = threading.Lock()
_last_my_state = None


def _push_state(state) -> None:
    global _last_my_state
    if state_queue.full():
        try:
            state_queue.get_nowait()
        except Exception:
            pass
    try:
        state_queue.put_nowait(state)
    except Exception:
        pass
    with _last_my_state_lock:
        _last_my_state = state


def _wake():
    """Re-push the last cached GameState so the consumer re-renders after a
    shadow mutation that had no fresh GameStatus."""
    with _last_my_state_lock:
        s = _last_my_state
    if s is None:
        return
    _push_state(s)


def _mutate_my_hand(slot: int, new_card_id: int, new_level: int = 1):
    with _last_my_state_lock:
        base = _last_my_state
    if base is None:
        return None
    me_idx = base.me_index
    if me_idx < 0 or me_idx >= len(base.players):
        return None
    new_state = copy.deepcopy(base)
    me = new_state.players[me_idx]
    for c in me.cards:
        if c.slot == slot:
            c.id = new_card_id
            c.name = card_name(new_card_id)
            c.level = new_level
            return new_state
    me.cards.append(CardState(id=new_card_id, name=card_name(new_card_id),
                              level=new_level, slot=slot))
    return new_state


# ─── S→C handlers (mutate shadow) ─────────────────────────────────────────────
def _handle_replace_card_resp(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "ReplaceCardResp":
        return
    pb = _decode_pb(inner.get("data", ""))
    new_info = pb.get("2") if isinstance(pb.get("2"), dict) else None
    if not isinstance(new_info, dict):
        return
    slot = int(new_info.get("2", 0) or 0)
    new_id = int(new_info.get("3", 0) or 0)
    if not new_id:
        return
    # NB: the server omits `slot` on most prep-phase rerolls (e.g. Painter
    # side-job rerolls), so we must NOT gate on `slot` — that previously
    # dropped half the ReplaceCardResps and corrupted the shadow board.
    # pb["3"] = {2: slot, 3: old_id} — the discarded card (rerolled away).
    old_info = pb.get("3") if isinstance(pb.get("3"), dict) else {}
    old_id = int(old_info.get("3", 0) or 0) if isinstance(old_info, dict) else 0
    reroll_events.append({
        "old": card_name(old_id) if old_id else None,
        "new": card_name(new_id),
    })
    shadow_state.apply_replace_resp(pb, name_fn=card_name)
    # R36: always re-render. Without this, slot==0 rerolls (common on prep-
    # phase / Painter side-job rerolls) mutated the shadow but never pushed
    # to the UI, so "cards left in deck" stayed stale until the next
    # MoveCardReq happened to wake the consumer.
    _wake()
    if slot:
        new_state = _mutate_my_hand(slot, new_id, new_level=1)
        if new_state is not None:
            _push_state(new_state)
    return f"ReplaceCardResp: slot {slot} → {card_name(new_id)}"


def _handle_refine_card_resp(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "RefineCardResp":
        return
    pb = _decode_pb(inner.get("data", ""))
    payload = pb.get("3") if isinstance(pb.get("3"), dict) else None
    if not isinstance(payload, dict):
        return
    card_id = int(payload.get("3", 0) or 0)
    if not card_id:
        return
    shadow_state.apply_refine_resp(pb, name_fn=card_name)
    _wake()
    return f"RefineCardResp: ABSORB {card_name(card_id)}"


def _handle_card_operation_resp(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "CardOperationResp":
        return
    pb = _decode_pb(inner.get("data", ""))
    shadow_state.apply_card_operation_resp(pb)
    _wake()
    return "CardOperationResp: card move applied"


def _handle_pending_daoyun(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "PendingDaoYunResp":
        return
    pb = _decode_pb(inner.get("data", ""))
    b = pb.get("3", b"") if isinstance(pb, dict) else b""
    if not isinstance(b, (bytes, bytearray)):
        return
    options = []
    for v in shadow_state.decode_varint_list(b):
        if v >= 1_000_000:
            options.append(shadow_state.ZoneCard(
                id=v, name=card_name(v), level=shadow_state._level_from_id(v)))
    if not options:
        return
    shadow_state.set_pending_choice(shadow_state.PendingChoice(
        kind="daoyun", options=options,
        prompt_text="Pick ONE (DaoYun): " + ", ".join(c.name for c in options)))
    _wake()
    return f"PendingDaoYunResp: {[c.name for c in options]}"


def _handle_pending_talent(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "PendingTalentResp":
        return
    pb = _decode_pb(inner.get("data", ""), typedef=_PENDINGTALENT_TYPEDEF)
    b = pb.get("1", b"") if isinstance(pb, dict) else b""
    if not isinstance(b, (bytes, bytearray)):
        return
    ids = shadow_state.decode_varint_list(b)
    if not ids:
        return
    options = [shadow_state.ZoneCard(id=fid, name=shadow_state.fate_name(fid), level=1)
               for fid in ids]
    shadow_state.set_pending_choice(shadow_state.PendingChoice(
        kind="fate", options=options,
        prompt_text="Pick ONE fate (天命): " + ", ".join(c.name for c in options)))
    _wake()
    return f"PendingTalentResp: fates {[c.name for c in options]}"


def _handle_battle_result(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "BattleResult":
        return
    pb = _decode_pb(inner.get("data", ""))
    if not isinstance(pb, dict):
        return

    def _uid(v):
        if isinstance(v, (bytes, bytearray)):
            return v.decode("utf-8", "replace")
        return str(v) if v is not None else ""

    global last_battle, my_last_opponent
    last_battle = {"winner": _uid(pb.get("8")), "loser": _uid(pb.get("9"))}
    me = _get_me_uid()
    if me and me in (last_battle["winner"], last_battle["loser"]):
        other = last_battle["loser"] if me == last_battle["winner"] else last_battle["winner"]
        if other:
            my_last_opponent = other
        return f"BattleResult: you {'WON' if me == last_battle['winner'] else 'LOST'}"
    return None


def _handle_player_data(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "PlayerData":
        return
    pb = _decode_pb(inner.get("data", ""), typedef=_PLAYERDATA_TYPEDEF)
    if not isinstance(pb, dict):
        return
    pdict = pb.get("1") if isinstance(pb.get("1"), dict) else None
    if not isinstance(pdict, dict):
        return
    me_uid = _get_me_uid()
    if not me_uid:
        return
    uid_raw = pdict.get("1", b"")
    uid = (uid_raw.decode("utf-8", "replace")
           if isinstance(uid_raw, (bytes, bytearray)) else str(uid_raw))
    if uid != me_uid:
        return

    from game_state import PlayerState, _parse_cards, _to_str, parse_player_stats
    xiuwei, tipo, realm_tier = parse_player_stats(pdict.get("200", {}))
    next_opp = pdict.get("9")
    prev_opp = pdict.get("10")
    # R27: keep `hp_field` (top-level [5] HP candidate) in sync on the
    # PlayerData refresh too, otherwise it'd reset to 0 between GameStatus
    # frames and the diagnostic side-by-side would flicker.
    hp_field = int(pdict.get("5", 0) or 0)
    # R28: also keep display_name in sync so BattleLog.json lookups work
    # when PlayerData fires between GameStatus frames.
    display_name = _to_str(pdict.get("2", "")) if pdict.get("2") else ""
    player = PlayerState(
        player_id=_to_str(pdict.get("1", "?")),
        destiny=int(pdict.get("100", 0) or 0),
        cards=_parse_cards(pdict.get("103", [])),
        display_name=display_name,
        xiuwei=xiuwei, tipo=tipo, realm_tier=realm_tier,
        hp=40 + xiuwei,
        hp_field=hp_field,
        next_opponent_id=_to_str(next_opp) if next_opp else "",
        prev_opponent_id=_to_str(prev_opp) if prev_opp else "",
    )
    player.raw = pdict

    team_container = None
    pb2 = pb.get("2")
    if isinstance(pb2, dict):
        uid_b = pb2.get("200", b"")
        uid_s = (uid_b.decode("utf-8", "replace")
                 if isinstance(uid_b, (bytes, bytearray)) else str(uid_b))
        if uid_s == me_uid:
            team_container = pb2

    # Reroll-remaining lives in team_container field 4.
    if team_container is not None:
        player.rerolls = int(team_container.get("4", 0) or 0)

    shadow_state.reset_from_player(player, name_fn=card_name,
                                   source="PlayerData", team_container=team_container)
    shadow_state.clear_pending_choice()
    _wake()
    return f"PlayerData: shadow refreshed (uid={uid[:8]}…)"


# ─── C→S handlers (mutate shadow) ─────────────────────────────────────────────
def _handle_move_card_req(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "MoveCardReq":
        return
    pb = _decode_pb(inner.get("data", ""))
    if not (pb.get("2") is not None or pb.get("3") is not None or pb.get("4") is not None):
        return
    shadow_state.apply_move_card(pb)
    _wake()
    return None


def _handle_insert_card_req(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "InsertCardReq":
        return
    pb = _decode_pb(inner.get("data", ""))
    shadow_state.apply_insert_card(pb)
    _wake()
    return "InsertCardReq: shadow board updated"


def _handle_simple_client_pact(mp):
    """SimpleClientPact (C→S): the client confirms a discrete choice as
    {1: kind, 2: chosen_id}. When a fate (天命) choice is pending and the
    chosen id matches one of the offered fates, record it for the damage sim."""
    inner = _inner(mp)
    if not inner or inner.get("type") != "SimpleClientPact":
        return
    pb = _decode_pb(inner.get("data", ""))
    if not isinstance(pb, dict):
        return
    chosen = int(pb.get("2", 0) or 0)
    if not chosen:
        return
    pc = shadow_state.get_pending_choice()
    if pc is not None and getattr(pc, "kind", "") == "fate":
        option_ids = {getattr(o, "id", None) for o in getattr(pc, "options", [])}
        if chosen in option_ids:
            chosen_fates.append(chosen)
            shadow_state.clear_pending_choice()
            _wake()
            return f"Fate chosen: {shadow_state.fate_name(chosen)} ({chosen})"
    return None


def _handle_select_career_req(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "SelectCareerReq":
        return
    pb = _decode_pb(inner.get("data", ""))
    cid = int(pb.get("1", 0) or 0) if isinstance(pb, dict) else 0
    if not cid:
        return
    shadow_state.note_career_pick(cid)
    return f"SelectCareerReq → career {cid} ({shadow_state.career_name(cid)})"


# ─── GameStatus → GameState push ──────────────────────────────────────────────
def _try_push_game_state(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "GameStatus":
        return None
    pb = _decode_pb(inner.get("data", ""), typedef=_GAMESTATUS_TYPEDEF)
    if not pb:
        return None

    # Auto-detect the user's UID from their own team container (pb["6"]).
    f6 = pb.get("6")
    if isinstance(f6, dict) and isinstance(f6.get("1"), (bytes, bytearray)) \
            and isinstance(f6.get("2"), (bytes, bytearray)):
        uid_b = f6.get("200", b"")
        uid_s = (uid_b.decode("utf-8", "replace")
                 if isinstance(uid_b, (bytes, bytearray)) else str(uid_b))
        if uid_s and len(uid_s) >= 16 and uid_s != _get_me_uid():
            _set_me_uid(uid_s)

    me_uid = _get_me_uid()
    state = parse_game_state(pb, phase="prep", me_uid=me_uid)
    is_my_game = bool(me_uid) and state.me_index >= 0

    if is_my_game:
        shadow_state.reset_from_player(
            state.players[state.me_index], name_fn=card_name,
            source="GameStatus", team_container=state.team_container or None)
        if shadow_state.shadow is not None:
            shadow_state.shadow.round_num = state.round_num
        _push_state(state)
        return f"GameStatus pushed — round {state.round_num}, {len(state.players)} players"
    return None


def process_msgpack(mp, from_client: bool):
    """Dispatch one decoded Colyseus msgpack payload through the shadow +
    state-queue handlers. Shared by the live websocket_message hook and the
    offline replay harness so both exercise identical logic."""
    if mp is None:
        return
    if not from_client:
        if _is_start_game_resp(mp):
            new_game_event.set()
            reroll_events.clear()
            chosen_fates.clear()
            # Drop any seasonal-parked cards so they don't leak into the new game
            # (seasonal is otherwise preserved across round resets within a game).
            if shadow_state.shadow is not None:
                shadow_state.shadow.seasonal.clear()
            with _last_my_state_lock:
                globals()["_last_my_state"] = None
        if _is_round_end(mp):
            round_ended_event.set()
        note = (_handle_replace_card_resp(mp)
                or _handle_refine_card_resp(mp)
                or _handle_card_operation_resp(mp)
                or _handle_pending_daoyun(mp)
                or _handle_pending_talent(mp)
                or _handle_battle_result(mp)
                or _handle_player_data(mp))
        if note:
            _log(note)
    else:
        note = (_handle_move_card_req(mp)
                or _handle_insert_card_req(mp)
                or _handle_simple_client_pact(mp)
                or _handle_select_career_req(mp))
        if note:
            _log(note)

    status = _try_push_game_state(mp)
    if status:
        _log(status)


# ─── Diagnostic capture (opt-in via YX_CAPTURE=1) ─────────────────────────────
# Records every non-heartbeat WS frame to proxy/output/traffic.jsonl (same shape
# the offline replay/analysis tools expect) and writes a running message-type
# tally to proxy/output/unhandled_types.txt, flagging types no handler consumes.
# Additive logging only — does not alter decoding or tracking behavior.
# Default OFF (opt-in). Set YX_CAPTURE=1 to enable, or use run_live.ps1 -Capture.
# Was default-ON during the tracking-debug phase, but that caused replay runs
# (which import addon) to silently truncate prior captures. Now opt-in.
CAPTURE = os.environ.get("YX_CAPTURE", "0") != "0"
_CAPTURE_DIR = Path(__file__).resolve().parent / "output"
_TRAFFIC_PATH = _CAPTURE_DIR / "traffic.jsonl"
_UNHANDLED_PATH = _CAPTURE_DIR / "unhandled_types.txt"

# Message types our handlers actually consume (for the unhandled tally).
_HANDLED_TYPES = {
    # S→C
    "GameStatus", "ReplaceCardResp", "RefineCardResp", "CardOperationResp",
    "PendingDaoYunResp", "PendingTalentResp", "BattleResult", "PlayerData",
    "StartGameResp",
    # C→S
    "MoveCardReq", "InsertCardReq", "SimpleClientPact", "SelectCareerReq",
}
# Pure transport/lobby heartbeats — never card-affecting; skipped to keep the
# capture small.
_CAPTURE_SKIP = {"Ping", "Pong"}

_capture_lock = threading.Lock()
_type_tally: dict = {}        # (direction, type) -> count
_capture_frames = 0

if CAPTURE:
    try:
        _CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        _TRAFFIC_PATH.write_text("", encoding="utf-8")       # fresh per session
        _UNHANDLED_PATH.write_text("", encoding="utf-8")
        print(f"[capture] ON → writing frames to {_TRAFFIC_PATH}", flush=True)
    except Exception:
        pass
else:
    print("[capture] OFF (set YX_CAPTURE=1 / use run_live.ps1 -Capture to record)",
          flush=True)


def _flush_unhandled():
    try:
        lines = ["# message-type tally for this capture session",
                 "#   '*' = a handler consumes it; 'x' = received but ignored", ""]
        for (direction, mtype), count in sorted(_type_tally.items(), key=lambda kv: -kv[1]):
            mark = "* " if mtype in _HANDLED_TYPES else "x "
            lines.append(f"{mark}{count:6d}  {direction:14s} {mtype}")
        _UNHANDLED_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def _capture_frame(mp, from_client: bool):
    """Append one decoded frame to traffic.jsonl and tally its type. Live-only
    (called from websocket_message), never during replay."""
    global _capture_frames
    inner = (mp[1] if isinstance(mp, list) and len(mp) > 1 and isinstance(mp[1], dict)
             else None)
    mtype = inner.get("type") if inner else None
    if mtype in _CAPTURE_SKIP:
        return
    direction = "client->server" if from_client else "server->client"
    event = {
        "type": "ws_frame",
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "direction": direction,
        "decoded": {"msgpack": mp},
    }
    with _capture_lock:
        try:
            with _TRAFFIC_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass
        key = (direction, mtype or "?")
        _type_tally[key] = _type_tally.get(key, 0) + 1
        _capture_frames += 1
        do_flush = (_capture_frames % 20 == 0)
        count = _capture_frames
    if do_flush:
        _flush_unhandled()
        print(f"[capture] {count} frames recorded", flush=True)


def _capture_undecoded(raw, from_client: bool):
    """Record a binary WS frame that produced no msgpack, so we can see whether
    missing actions are decode failures (these appear) vs dropped frames (gaps
    in timestamps with nothing here)."""
    direction = "client->server" if from_client else "server->client"
    try:
        data = bytes(raw)
    except Exception:
        return
    event = {
        "type": "ws_undecoded",
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "direction": direction,
        "len": len(data),
        "hex": data[:512].hex(),
    }
    with _capture_lock:
        try:
            with _TRAFFIC_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass
        _type_tally[(direction, "<undecoded>")] = _type_tally.get((direction, "<undecoded>"), 0) + 1


# ─── The mitmproxy addon ──────────────────────────────────────────────────────
class YiXianInterceptor:
    def response(self, flow):
        if TARGET_HOST not in flow.request.pretty_host or flow.response is None:
            return
        if "application/json" not in flow.response.headers.get("content-type", ""):
            return
        if "/auth/login" not in flow.request.pretty_url:
            return
        try:
            body = json.loads(flow.response.text)
            uid = body.get("data", {}).get("userInfo", {}).get("uid", "")
            if uid:
                _set_me_uid(uid)
        except Exception:
            pass

    def websocket_message(self, flow):
        if TARGET_HOST not in flow.request.pretty_host:
            return
        msg = flow.websocket.messages[-1]
        is_binary = (isinstance(msg.content, (bytes, bytearray))
                     and getattr(msg.type, "value", msg.type) == 2)
        if not is_binary:
            return

        mp = decode_frame(msg.content).get("msgpack")
        if CAPTURE:
            if mp is None:
                # A binary frame we couldn't turn into msgpack — record it so we
                # can tell whether missing actions are decode failures vs truly
                # absent (dropped) frames.
                _capture_undecoded(msg.content, msg.from_client)
            else:
                _capture_frame(mp, msg.from_client)
        process_msgpack(mp, msg.from_client)

    def done(self):
        if CAPTURE:
            _flush_unhandled()


addons = [YiXianInterceptor()]
