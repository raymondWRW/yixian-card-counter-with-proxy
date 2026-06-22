"""
proxy_runtime.py — legacy mitmproxy-based live capture.

The current main app uses frida to hook the game's ProtobufParser inside the
process (no cert, no admin needed). This module is kept for the older method
that MITMs the TLS connection — useful when frida is blocked (anticheat,
locked-down env) or for diagnostic capture (mitmdump's traffic.jsonl writer).

Set YX_PROXY=1 when launching app.py to use this path instead of frida.
"""
from pathlib import Path
import sys

# Make the parent project's `proxy/` package importable. This file lives in
# `proxy[outdated]/`; parent is the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROXY_PKG = _REPO_ROOT / "proxy"
if str(_PROXY_PKG) not in sys.path:
    sys.path.insert(0, str(_PROXY_PKG))

import addon  # noqa: E402  (proxy/addon.py — YiXianInterceptor lives here)


def start_proxy(listen_port: int = 8080):
    """Run mitmproxy in local mode on this thread (call from a daemon thread).

    Requires: admin (for WinDivert) AND the mitmproxy CA cert installed in
    the Windows Trusted Root store (run cert_setup.py once)."""
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
