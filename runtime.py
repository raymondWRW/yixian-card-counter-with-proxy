"""
runtime.py
──────────
Wires the ported proxy package to the app. Three entry points:

  start_frida_capture()   — frida-spawn the game, hook ProtobufParser, feed
                            messages into the same decode/shadow/Counter
                            pipeline. No cert, no admin. Default live source.
  start_consumer(push)    — drain state_queue, build a view-model, push to UI.
  replay(path[, limit])   — feed a captured traffic.jsonl through the same
                            decode→shadow→state path offline. For development /
                            verification.

The legacy mitmproxy-based `start_proxy()` lives in
`proxy[outdated]/proxy_runtime.py` and is opt-in via `YX_PROXY=1`.

CLI:  python runtime.py replay ["path\to\traffic.jsonl"] [limit]
"""
import json
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROXY_DIR = BASE_DIR / "proxy"

# The ported modules use top-level absolute imports (`import shadow_state`),
# so proxy/ must be importable as top-level. Insert once, before importing.
if str(PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(PROXY_DIR))

import addon                      # noqa: E402  (proxy/addon.py)
import shadow_state               # noqa: E402
from state_queue import state_queue, new_game_event, round_ended_event  # noqa: E402


# ─── Consumer: state_queue → view-model → UI ──────────────────────────────────
def start_consumer(push):
    """Drain GameState objects and push view-models to the UI via `push`."""
    from proxy_view import build_view_model, Counter, OpponentTracker
    counter = Counter()
    opp_tracker = OpponentTracker()
    while True:
        try:
            state = state_queue.get(timeout=0.5)
        except Exception:
            continue
        if new_game_event.is_set():
            new_game_event.clear()
            counter.reset()
            opp_tracker.reset()
        if round_ended_event.is_set():
            round_ended_event.clear()
        try:
            counter.observe(state)
            opp_tracker.observe(state)
            vm = build_view_model(state, counter=counter,
                                  last_battle=addon.last_battle, opp_tracker=opp_tracker)
            push(vm)
            # YX_DEBUG=1: also persist this view-model into the per-game
            # battle_log/<timestamp>/deck_tracker.jsonl for offline analysis.
            try:
                addon.write_deck_tracker_snapshot(vm)
            except Exception:
                pass
        except Exception as e:
            print(f"[consumer] view-model build failed: {e}")


# Live capture via mitmproxy was moved to `proxy[outdated]/proxy_runtime.py`
# (legacy method — needs cert + admin). The main app now defaults to frida.


# ─── Live capture via frida (no cert / no admin) ──────────────────────────────
def start_frida_capture(game_exe: str = None, attach_mode: bool = False):
    """Spawn YiXianPai through frida and hook ProtobufParser to feed messages
    into `addon.process_msgpack` — the same pipeline `start_proxy` populates,
    but bypassing TLS/mitmproxy entirely (no cert, no admin).

    Args:
        game_exe: Path to YiXianPai.exe. If None, falls back to the
                  `YX_GAME_EXE` env var.
        attach_mode: If True, attach to an already-running game instead of
                     spawning. Counter accuracy depends on attaching BEFORE
                     the match starts (the opening deal must be observed).

    Designed to be called from a daemon thread; it blocks forever to keep the
    frida session (and its script's hooks) alive.
    """
    import os
    import time
    import frida

    capture_agent = BASE_DIR / "native_hud" / "_build" / "capture.agent.js"
    if not capture_agent.exists():
        raise FileNotFoundError(f"capture agent not found: {capture_agent}")
    agent_src = capture_agent.read_text(encoding="utf-8")

    def on_message(msg, _data):
        """frida → addon.process_msgpack. The agent sends
        {dir: 'in'|'out', t: typeName, b: base64} for every protobuf
        encode/decode the game performs."""
        if msg.get("type") != "send":
            return
        p = msg.get("payload") or {}
        t, b, d = p.get("t"), p.get("b"), p.get("dir", "in")
        if not t:
            return
        try:
            addon.process_msgpack(["data", {"type": t, "data": b}],
                                  from_client=(d == "out"))
        except Exception as e:
            print(f"[frida] process_msgpack failed: {e}", flush=True)

    if attach_mode:
        proc = os.environ.get("YX_PROC", "YiXianPai.exe")
        print(f"[frida] attach {proc}", flush=True)
        session = frida.attach(proc)
        pid = None
    else:
        if not game_exe:
            game_exe = os.environ.get("YX_GAME_EXE")
        if not game_exe or not Path(game_exe).exists():
            raise FileNotFoundError(
                "game exe not found; pass game_exe= or set YX_GAME_EXE")
        print(f"[frida] spawn {game_exe}", flush=True)
        pid = frida.spawn([game_exe])
        session = frida.attach(pid)

    script = session.create_script(agent_src, runtime="qjs")
    script.on("message", on_message)
    script.load()
    if pid is not None:
        frida.resume(pid)
    print("[frida] capture active (ProtobufParser hooked, "
          "feeding state_queue)", flush=True)
    # Keep the session/script alive forever. The on_message callback fires
    # on frida's internal thread; this loop just blocks the caller thread.
    while True:
        time.sleep(60)


# ─── Offline replay of a captured traffic.jsonl ───────────────────────────────
# Default replay source: a capture under the project's (gitignored) proxy/output.
# Override by passing a path to replay()/the CLI, or via YX_REPLAY_PATH.
DEFAULT_CAPTURE = BASE_DIR / "proxy" / "output" / "traffic.jsonl"


def replay(path=None, limit=0, on_state=None):
    """Feed captured ws frames through addon.process_msgpack in order.

    on_state(state) is called for every GameState pushed onto state_queue.
    Returns the count of GameStatus states seen.
    """
    path = Path(path or DEFAULT_CAPTURE)
    seen = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("type") != "ws_frame":
                continue
            dec = e.get("decoded") or {}
            mp = dec.get("msgpack")
            if mp is None:
                continue
            from_client = e.get("direction") == "client->server"
            addon.process_msgpack(mp, from_client)
            # Drain anything the handlers pushed.
            while not state_queue.empty():
                state = state_queue.get_nowait()
                seen += 1
                if on_state:
                    on_state(state)
                if limit and seen >= limit:
                    return seen
    return seen


def start_replay_ui(push, path=None, delay=0.25, limit=0):
    """Drive the live UI from a captured traffic.jsonl (dev/demo, no admin).

    Builds the same view-models the live consumer would and pushes them with
    a small delay so the session plays back visibly.
    """
    from proxy_view import build_view_model, Counter, OpponentTracker
    import addon
    counter = Counter()
    opp_tracker = OpponentTracker()

    def on_state(state):
        if new_game_event.is_set():
            new_game_event.clear()
            counter.reset()
            opp_tracker.reset()
        if round_ended_event.is_set():
            round_ended_event.clear()
        counter.observe(state)
        opp_tracker.observe(state)
        vm = build_view_model(state, counter=counter,
                              last_battle=addon.last_battle, opp_tracker=opp_tracker)
        push(vm)
        if delay:
            time.sleep(delay)

    replay(path, limit=limit, on_state=on_state)
    print("[replay-ui] playback finished")


def _print_state(state):
    sh = shadow_state.shadow
    line = [f"R{state.round_num} phase={state.phase} players={len(state.players)} me_idx={state.me_index}"]
    if state.me_index >= 0 and sh is not None:
        unlocked = shadow_state.unlocked_board_slots(state.round_num)
        hand = ", ".join(f"{c.name}{'·lv'+str(c.level) if c.level>1 else ''}"
                         for c in sh.hand if c) or "(empty)"
        board = ", ".join((c.name if c else "·") for c in sh.board[:unlocked])
        me = state.players[state.me_index]
        line.append(f"  YOU 命{me.destiny} 修{sh.xiuwei} 体{sh.tipo} 境{sh.realm_tier}")
        line.append(f"    hand: {hand}")
        line.append(f"    board[0..{unlocked-1}]: {board}")
    print("\n".join(line))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = sys.argv[1:]
    if args and args[0] == "replay":
        p = args[1] if len(args) > 1 else None
        lim = int(args[2]) if len(args) > 2 else 0
        t0 = time.time()
        n = replay(p, limit=lim, on_state=_print_state)
        print(f"\n[replay] {n} GameState pushes in {time.time()-t0:.1f}s")
    else:
        print(__doc__)
