# -*- coding: utf-8 -*-
"""yixian_api: namespaced calls into the running 弈仙牌 game (via bot_glue3 RPC
+ YiXianApi.dll). Ported from the game-api branch.

    from native_hud.api import connect
    api = connect(attach=True)      # attach to a running game
    api.placement.board()           # -> {"hand": [{"slot":0,"id":1020001}, ...]}
    api.state.self()                # -> {"life":100,"maxHp":40,"tiPo":0,"level":1}

Or reuse an existing frida session (e.g. the live capture session):
    from native_hud.api import connect_via_session
    api = connect_via_session(session)
"""
import json
from .registry import API


class _Namespace:
    """A registry namespace's methods, bound to one rpc."""
    def __init__(self, rpc, specs):
        for s in specs:
            setattr(self, s.name, self._make(rpc, s))

    @staticmethod
    def _make(rpc, s):
        def method(*args):
            if len(args) != len(s.args):
                raise TypeError("%s.%s needs %d args, got %d"
                                % (s.namespace, s.name, len(s.args), len(args)))
            if s.call == "call_s":
                raw = rpc.call_s(s.ctype, s.cmethod, list(args))
            else:
                raw = rpc.call_str(s.ctype, s.cmethod, args[0] if args else "")
            return json.loads(raw) if s.ret == "json" else raw
        method.__name__ = s.name
        method.__doc__ = s.doc
        return method


class Client:
    """Exposes registry namespaces as attributes: client.placement.board() etc."""
    def __init__(self, rpc):
        self._rpc = rpc
        order = []
        for s in API:
            if s.namespace not in order:
                order.append(s.namespace)
        for ns in order:
            setattr(self, ns, _Namespace(rpc, [s for s in API if s.namespace == ns]))

    def close(self):
        if hasattr(self._rpc, "close"):
            self._rpc.close()


def connect(attach=False):
    """Spawn (or attach=True) the game, inject, return a Client."""
    from ._rpc import Rpc
    return Client(Rpc(attach=attach))


def connect_via_session(session):
    """Build a Client on an EXISTING frida.Session (shared with another agent,
    e.g. the live capture session). Loads its own bot_glue3 + YiXianApi.dll on
    that session; does not spawn/resume/detach it."""
    from ._rpc import Rpc
    return Client(Rpc(session=session))
