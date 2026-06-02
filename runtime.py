"""
runtime.py
──────────
Wires the ported proxy package to the app. Three entry points:

  start_proxy()           — run mitmproxy's DumpMaster (local/WinDivert mode)
                            on a background thread; needs admin. Live capture.
  start_consumer(push)    — drain state_queue, build a view-model, push to UI.
  replay(path[, limit])   — feed a captured traffic.jsonl through the same
                            decode→shadow→state path offline (no admin). For
                            development / verification.

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


# ─── Live proxy via embedded DumpMaster ───────────────────────────────────────
def start_proxy(listen_port: int = 8080):
    """Run mitmproxy in local mode on this thread (call from a daemon thread)."""
    import asyncio
    from mitmproxy.options import Options
    from mitmproxy.tools.dump import DumpMaster

    async def _run():
        # Scope the WinDivert redirect to ONLY YiXianPai.exe so other apps
        # (browsers, Discord, Steam, banking — anything with cert pinning)
        # continue working normally while the counter is open.
        opts = Options(mode=["local:YiXianPai.exe"], listen_port=listen_port)
        master = DumpMaster(opts, with_termlog=False, with_dumper=False)
        master.addons.add(addon.YiXianInterceptor())
        print(f"[proxy] mitmproxy local mode active (port {listen_port}, scope: YiXianPai.exe)")
        await master.run()

    try:
        asyncio.run(_run())
    except Exception as e:
        print(f"[proxy] stopped: {e}")


# ─── Offline replay of a captured traffic.jsonl ───────────────────────────────
DEFAULT_CAPTURE = Path(
    r"C:\Users\raymo\OneDrive\Desktop\yixian script\yixian-proxy\output\traffic.jsonl"
)


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
