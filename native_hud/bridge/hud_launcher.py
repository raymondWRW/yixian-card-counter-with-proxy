# -*- coding: utf-8 -*-
"""Full native-HUD launcher (spawn-inject).

Launches YiXianPai THROUGH frida (hook before frame 1 → counts correct from
round 1), then on ONE process runs two scripts:
  · capture.agent.js   — inbound/outbound protobuf → addon.process_msgpack →
                         Counter  (the 记牌器, reused proxy logic)
  · bot_glue3.agent.js — loads YiXianHud19.dll into the game's ILRuntime
                         AppDomain and exposes Show / SetRemaining
A consumer thread pushes Counter.remaining() (name-expanded for exact in-game
CardConfig.name match) to Hud19.SetRemaining, which draws 剩X on every card.

Run from a CLOSED game (spawn launches a fresh instance). Ctrl-C to stop.
"""
import sys
import os
import json
import time
import threading
import subprocess
from pathlib import Path

import frida

if getattr(sys, "frozen", False):
    REPO = Path(sys._MEIPASS)            # PyInstaller bundle root (data laid out to mirror repo)
else:
    REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "proxy", REPO / "autoplay" / "inject"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import addon                                                  # noqa: E402
import state_queue as _sq                                     # noqa: E402
from proxy_view import (Counter, OpponentTracker,             # noqa: E402
                        remaining_with_aliases, build_view_model)
from native_hud.bridge import _feed_writer                    # noqa: E402

BUILD = Path(os.environ.get("YX_HUD_BUILD", REPO / "native_hud" / "_build"))
CAPTURE = str(BUILD / "capture.agent.js")
GLUE = str(BUILD / "bot_glue3.agent.js")
HUD_DLL = str(BUILD / "YiXianHud23.dll")
NODE_MARGINAL = str(REPO / "native_hud" / "bridge" / "yisim_marginal.js")
GAME_NAME = "YiXianPai.exe"
HUD_T = "YiXianBot.Hud23"
# Earlier HUD iterations to hide on (re)load so only the current one draws.
OLD_HUDS = ["Hud22", "Hud21", "Hud20", "Hud19", "Hud18", "Hud17", "Hud16"]

# Live settings (toggled from the GUI). Loops read these each iteration.
SETTINGS = {
    "remaining": True,   # 记牌器 剩X
    "damage": True,      # T1..T8 造伤
    "opponent": True,    # 对手 命/修
    "warning": True,     # 危险牌警告
    "matchup": True,     # 伤害模式: True=matchup(vs对手), False=solo
}
WATCH = ("护身灵气", "灵气灌注", "震雷")
_SEP_NORM = str.maketrans({"•": "·"})           # runtime names mix • and ·
# Danger cards: if the opponent's board has any of these, flash a warning.
DANGER_CARDS = {
    "缚仙古藤", "噬仙古藤", "天音困仙曲", "幽绪乱心曲", "奇门锁妖塔",
    "猎枭古弓", "水灵·海龙啸", "影枭兔", "幽冥虚魂犬", "噬灵虚兽",
}


def _card_name(c):
    return (c.get("name") if isinstance(c, dict) else c) or ""


# ── Game-exe resolution (no hardcoded path) ───────────────────────────────────
def _exe_dir():
    """Folder the launcher/exe lives in (where the game and config sit)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _config_path():
    return _exe_dir() / "YiXianHUD_config.json"


def _load_cfg():
    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cfg(cfg):
    try:
        _config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _ask_game_exe():
    """Pop a file picker so the user selects YiXianPai.exe."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk()
        r.withdraw()
        r.attributes("-topmost", True)
        p = filedialog.askopenfilename(
            title="找不到游戏 — 请选择 YiXianPai.exe",
            filetypes=[("弈仙牌", "YiXianPai.exe"), ("可执行文件", "*.exe")])
        r.destroy()
        return p or None
    except Exception:
        return None


def resolve_game_exe():
    """Find the game exe: env override → same folder as us → remembered choice →
    ask the user (and remember it). Returns a path or None if the user cancels."""
    p = os.environ.get("YX_GAME_EXE")
    if p and os.path.exists(p):
        return p
    same = _exe_dir() / GAME_NAME
    if same.exists():
        return str(same)
    cfg = _load_cfg()
    saved = cfg.get("game_exe")
    if saved and os.path.exists(saved):
        return saved
    chosen = _ask_game_exe()
    if chosen and os.path.exists(chosen):
        cfg["game_exe"] = chosen
        _save_cfg(cfg)
        return chosen
    return None


_NODE = {"exe": None}


def node_exe():
    """node for the yisim sim: bundled node.exe (frozen) first so the published
    exe works WITHOUT node installed; else fall back to a system node."""
    if _NODE["exe"]:
        return _NODE["exe"]
    import shutil
    cand = None
    if getattr(sys, "frozen", False):
        b = Path(sys._MEIPASS) / "node.exe"
        if b.exists():
            cand = str(b)
    if not cand:
        cand = shutil.which("node")
    if not cand:
        for p in (r"C:\Program Files\nodejs\node.exe",
                  os.path.expandvars(r"%ProgramFiles%\nodejs\node.exe"),
                  os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs\node.exe")):
            if p and os.path.exists(p):
                cand = p
                break
    _NODE["exe"] = cand or "node"
    return _NODE["exe"]


_counts = {"in": 0, "out": 0}
_hud_ex = {"ex": None}
_hud_ready = threading.Event()
_latest = {"vm": None}


def on_feed(msg, _data):
    if msg.get("type") != "send":
        return
    p = msg.get("payload") or {}
    t, b, d = p.get("t"), p.get("b"), p.get("dir", "in")
    if not t:
        return
    _counts["in" if d == "in" else "out"] += 1
    # Record the raw event so it can be replayed offline through
    # addon.process_msgpack to rebuild battle_log/<game_ts>/ folders for the
    # Review window. See native_hud/bridge/_feed_writer.py.
    _feed_writer.write_event(d, t, b)
    try:
        addon.process_msgpack(["data", {"type": t, "data": b}], from_client=(d == "out"))
    except Exception:
        pass


def hud_loader():
    """Load the HUD DLL once the ILRuntime AppDomain is ready, then Show.
    Load and Show are retried separately: LoadAssembly only once (re-loading the
    same assembly errors), but Show is retried until it actually subscribes
    (early invokes can hit a transient 'system error' before the scene is up)."""
    ex = _hud_ex["ex"]

    def hide_olds():
        for old in OLD_HUDS:
            try:
                ex.call_s("YiXianBot." + old, "Hide", [])
            except Exception:
                pass

    for _ in range(80):
        # 1) Already loaded (re-attach to a game we set up before)? Show works
        #    immediately — DON'T re-load the assembly: re-loading stacks a second
        #    tick → duplicate labels. Reuse it and we're done.
        try:
            s = ex.call_s(HUD_T, "Show", [])
            if s and s.get("ok") and str(s.get("result", "")).startswith("ok"):
                print("[hud] reuse (already loaded) ->", s, flush=True)
                hide_olds()
                _hud_ready.set()
                return
        except Exception:
            pass
        # 2) Not loaded yet → load the assembly, hide older iterations, then Show.
        try:
            with open(HUD_DLL, "rb") as f:
                r = ex.load_bot(f.read())
            if r and r.get("ok"):
                print("[hud] assembly loaded", flush=True)
                hide_olds()
                try:
                    s = ex.call_s(HUD_T, "Show", [])
                    if s and s.get("ok") and str(s.get("result", "")).startswith("ok"):
                        print("[hud] Show ->", s, flush=True)
                        _hud_ready.set()
                        return
                except Exception:
                    pass
        except Exception as e:
            print("[hud] load err", e, flush=True)
        time.sleep(3)


def consumer():
    counter = Counter()
    opp = OpponentTracker()
    last_round = [0]
    while True:
        try:
            state = _sq.state_queue.get(timeout=0.5)
        except Exception:
            continue
        rn = int(getattr(state, "round_num", 0) or 0)
        if _sq.new_game_event.is_set() or (last_round[0] > 1 and rn <= 1):
            try:
                _sq.new_game_event.clear()
            except Exception:
                pass
            counter.reset()
            opp.reset()
            print("[reset] 新局 (round %d->%d)" % (last_round[0], rn), flush=True)
        last_round[0] = rn
        try:
            counter.observe(state)
            opp.observe(state)
            vm = build_view_model(state, counter=counter,
                                  last_battle=addon.last_battle, opp_tracker=opp)
            _latest["vm"] = vm
            rem = (vm.get("counter") or {}).get("remaining") or {}
            print("[r%s] in=%d out=%d remaining=%d keys=%s"
                  % (rn, _counts["in"], _counts["out"], len(rem),
                     list(rem.keys())[:10]), flush=True)
            ex = _hud_ex["ex"]
            if ex is not None and _hud_ready.is_set():
                ex.call_str(HUD_T, "SetShowLeft", "1" if SETTINGS["remaining"] else "0")
                if rem:
                    payload = remaining_with_aliases(rem)
                    ex.call_str(HUD_T, "SetRemaining",
                                "|".join("%s:%s" % (k, v) for k, v in payload.items()))
                # Opponent HP cap + 修为. The tracked values are LAST round's;
                # user's rule: this round ≈ last HP +2, last 修为 +5.
                # NB: keep `opp` = the OpponentTracker (do NOT rebind it here, or
                # next round's opp.observe() blows up — use a separate name).
                opp_vm = vm.get("opponent")
                if opp_vm and SETTINGS["opponent"]:
                    ohp = int(opp_vm.get("hp") or 0) + 2
                    oxw = int(opp_vm.get("xiuwei") or 0) + 5
                    ex.call_str(HUD_T, "SetOpponent", "敌 命%d 修%d (预估)" % (ohp, oxw))
                else:
                    ex.call_str(HUD_T, "SetOpponent", "")
                names = {_card_name(c).translate(_SEP_NORM)
                         for c in ((opp_vm or {}).get("board") or []) if c}
                danger = sorted(names & DANGER_CARDS)
                if danger and SETTINGS["warning"]:
                    ex.call_str(HUD_T, "SetWarning", "⚠ 对手危险牌: " + " ".join(danger))
                else:
                    ex.call_str(HUD_T, "SetWarning", "")
        except Exception as e:
            print("[consumer] %s" % e, flush=True)


def total_loop():
    """Whole-board yisim damage (the SAME number the web tool shows: 8-turn
    cumulative), fed the same inputs the web does (board levels + 仙命/天衍
    talents + deckSlots). Pushed to Hud19.SetTotal (screen-anchored)."""
    while True:
        try:
            vm = _latest["vm"]
            me = (vm or {}).get("me") or {}
            board = me.get("board") or []
            ex = _hud_ex["ex"]
            if ex is not None and _hud_ready.is_set() and not SETTINGS["damage"]:
                ex.call_str(HUD_T, "SetTotal", "")   # damage display off
                time.sleep(1.0)
                continue
            if ex is not None and _hud_ready.is_set() and any(c for c in board) \
                    and not (me.get("lingyuUnresolved")):
                obj = {
                    "totalOnly": True,
                    "board": board,
                    "talents": me.get("fates") or [],
                    "deckSlots": me.get("unlocked") or len(board) or 8,
                }
                # MATCHUP: if enabled AND we know the opponent's (last-seen) board,
                # sim real combat against it so the damage reflects THIS opponent.
                opp_vm = (vm or {}).get("opponent")
                oboard = (opp_vm or {}).get("board") or []
                if SETTINGS["matchup"] and opp_vm and any(c for c in oboard):
                    obj["opponent"] = {
                        "board": oboard,
                        "deckSlots": opp_vm.get("unlocked") or len(oboard) or 8,
                        "talents": opp_vm.get("fates") or [],
                        "playerState": {
                            "hp": opp_vm.get("hp"), "maxHp": opp_vm.get("hp"),
                            "physique": opp_vm.get("tipo") or 0,
                            "maxPhysique": opp_vm.get("tipo") or 0,
                            "cultivation": opp_vm.get("xiuwei") or 0,
                        },
                    }
                payload = json.dumps(obj, ensure_ascii=False)
                p = subprocess.run([node_exe(), NODE_MARGINAL], input=payload.encode("utf-8"),
                                   capture_output=True, timeout=25)
                res = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
                full = res.get("full")
                cum = res.get("cumulative") or []
                outcome = res.get("outcome")
                end_turn = res.get("endTurn")
                print("[total] mode=%s full=%s outcome=%s@T%s cumulative=%s"
                      % (res.get("mode"), full, outcome, end_turn, cum), flush=True)
                # outcome tag (matchup only): 必胜/可赢/会输 @Tn
                tag = ""
                if outcome == "win":
                    tag = "  %s@T%s" % ("必胜" if res.get("deterministic") else "可赢", end_turn)
                elif outcome == "lose":
                    tag = "  会输@T%s" % end_turn
                if cum:
                    txt = "  ".join("T%d %s" % (i + 1, v) for i, v in enumerate(cum)) + tag
                    ex.call_str(HUD_T, "SetTotal", txt)
                elif full is not None:
                    ex.call_str(HUD_T, "SetTotal", "造伤 %s%s" % (full, tag))
            time.sleep(1.5)
        except Exception as e:
            print("[total] %s" % e, flush=True)
            time.sleep(2)


PROCESS = os.environ.get("YX_PROC", "YiXianPai.exe")


def main():
    # YX_ATTACH=1 → attach to the ALREADY-RUNNING game (no spawn / no restart).
    # Damage/opponent/warning are correct immediately; 剩X is only fully correct
    # if attached before the match started (it needs the opening deal). Default
    # is spawn (launch the game ourselves → everything correct from round 1).
    # Default: SPAWN (launch the game through frida → hook before frame 1 → counts
    # correct from round 1). Set YX_ATTACH=1 to attach to an already-running game.
    attach_mode = os.environ.get("YX_ATTACH", "0") != "0"
    pid = None
    if attach_mode:
        print("attach %s (运行中的游戏)…" % PROCESS, flush=True)
        try:
            feed_session = frida.attach(PROCESS)
            hud_session = frida.attach(PROCESS)
        except Exception as e:
            print("\n[!] 挂载失败:%s" % e, flush=True)
            print("[!] 请先从 Steam 打开弈仙牌(到登录/大厅),再运行本程序。", flush=True)
            try:
                input("\n按回车键退出…")
            except Exception:
                pass
            return
    else:
        game_exe = resolve_game_exe()
        if not game_exe:
            print("[err] 未选择游戏路径,退出。", flush=True)
            return
        print("spawn %s …" % game_exe, flush=True)
        pid = frida.spawn([game_exe])
        feed_session = frida.attach(pid)
        hud_session = frida.attach(pid)
    # Open the per-session feed file BEFORE the capture agent loads so the
    # very first event lands in the recording.
    _sess_dir = _feed_writer.start_session()
    if _sess_dir:
        print("[feed] -> %s" % _sess_dir, flush=True)
    feed_script = feed_session.create_script(open(CAPTURE, encoding="utf-8").read(), runtime="qjs")
    feed_script.on("message", on_feed)
    feed_script.load()
    hud_script = hud_session.create_script(open(GLUE, encoding="utf-8").read(), runtime="qjs")
    hud_script.load()
    _hud_ex["ex"] = hud_script.exports_sync
    if not attach_mode:
        frida.resume(pid)
    print(">>> capture+glue 已挂 (%s). 进对局后自动加载HUD. Ctrl-C 停 <<<"
          % ("attach" if attach_mode else "spawn"), flush=True)
    threading.Thread(target=hud_loader, daemon=True).start()
    threading.Thread(target=consumer, daemon=True).start()
    threading.Thread(target=total_loop, daemon=True).start()

    def _cleanup():
        # Snapshot the game's BattleLog.json + close the feed file BEFORE
        # detaching, so the Review window can convert this session offline.
        try:
            _feed_writer.end_session()
        except Exception:
            pass
        try:
            feed_session.detach()
            hud_session.detach()
        except Exception:
            pass
        if pid is not None:
            try:
                frida.kill(pid)
            except Exception:
                pass

    def _status():
        hud = "已挂✓" if _hud_ready.is_set() else "等待对局…"
        return "HUD: %s\nin=%d out=%d (%s)" % (
            hud, _counts["in"], _counts["out"], "attach" if attach_mode else "spawn")

    # GUI settings window (default). YX_NOGUI=1 → headless console (Ctrl-C to stop).
    if os.environ.get("YX_NOGUI", "0") != "0":
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        _cleanup()
    else:
        try:
            from hud_gui import run_gui
            run_gui(SETTINGS, on_exit=_cleanup, status_get=_status)
        except Exception as e:
            print("[gui] %s — 退回控制台(Ctrl-C 停)" % e, flush=True)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            _cleanup()


if __name__ == "__main__":
    main()
