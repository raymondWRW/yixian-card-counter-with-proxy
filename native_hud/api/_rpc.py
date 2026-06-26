# -*- coding: utf-8 -*-
"""底层管道:连游戏(spawn/attach 或复用已有 frida session)、加载 YiXianApi.dll、
等 AppDomain 就绪、经 bot_glue3 调 RPC。call_s/call_str 把 {ok,result,err} 解成字符串。

Ported from the game-api branch and extended: pass ``session=<frida.Session>``
to reuse an existing injection (e.g. the live capture session in
runtime.start_frida_capture) instead of spawning a second one."""
import os
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DLL = Path(os.environ.get("YX_API_DLL", REPO / "native_hud" / "_build" / "YiXianApi.dll"))
GLUE = Path(os.environ.get("YX_HUD_BUILD", REPO / "native_hud" / "_build")) / "bot_glue3.agent.js"
GAME = os.environ.get("YX_GAME_EXE", "")
PROC = os.environ.get("YX_PROC", "YiXianPai.exe")


class YiXianApiError(Exception):
    def __init__(self, ctype, cmethod, raw):
        super().__init__("%s.%s -> %s" % (ctype, cmethod, raw))
        self.ctype, self.cmethod, self.raw = ctype, cmethod, raw


def _unwrap(ctype, cmethod, r):
    """{ok,result,err} → result 字符串;失败抛 YiXianApiError。"""
    if not r or not r.get("ok"):
        raise YiXianApiError(ctype, cmethod, (r or {}).get("err", "rpc-failed"))
    res = r.get("result", "")
    if isinstance(res, str) and (res.startswith("EX:") or res.startswith("not found")):
        raise YiXianApiError(ctype, cmethod, res)
    return res


class Rpc:
    """RPC over a bot_glue3 frida script.

    - ``Rpc()``             — spawn YX_GAME_EXE and inject.
    - ``Rpc(attach=True)``  — attach to a running game.
    - ``Rpc(session=sess)`` — reuse an existing frida.Session (does NOT spawn /
                              resume / detach it; the owner manages its life).
    """

    def __init__(self, attach=False, session=None):
        import frida
        self._owns_session = session is None
        pid = None
        if session is None:
            if attach:
                session = frida.attach(PROC)
            else:
                if not GAME or not os.path.exists(GAME):
                    raise FileNotFoundError("game exe not found; set YX_GAME_EXE")
                pid = frida.spawn([GAME])
                session = frida.attach(pid)
        self._sess = session
        self._sc = session.create_script(GLUE.read_text(encoding="utf-8"), runtime="qjs")
        self._sc.load()
        self._ex = self._sc.exports_sync
        if pid is not None:
            frida.resume(pid)
        self._load_dll()

    def _load_dll(self):
        if not DLL.exists():
            raise FileNotFoundError("YiXianApi.dll not found: %s" % DLL)
        data = DLL.read_bytes()
        # 轮询到 AppDomain 就绪:load_bot 在未就绪时返回非 ok,重试。
        for _ in range(120):
            try:
                r = self._ex.load_bot(data)
                if r and r.get("ok"):
                    return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError("YiXianApi.dll load timed out (AppDomain not ready)")

    def call_s(self, ctype, cmethod, ints):
        return _unwrap(ctype, cmethod,
                       self._ex.call_s(ctype, cmethod, [int(x) for x in ints]))

    def call_str(self, ctype, cmethod, s):
        return _unwrap(ctype, cmethod, self._ex.call_str(ctype, cmethod, s))

    def close(self):
        try:
            self._sc.unload()
        except Exception:
            pass
        if self._owns_session:
            try:
                self._sess.detach()
            except Exception:
                pass
