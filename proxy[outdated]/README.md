# proxy[outdated] — legacy mitmproxy-based capture

The main app now defaults to **frida** to hook the game's `ProtobufParser`
inside the process — no cert, no admin, no WinDivert. This folder is the
**original** approach kept for fallback / archive.

## When to use this

- frida won't attach (anticheat, locked-down env, AV blocks)
- You want a `traffic.jsonl` recording for offline analysis (mitmproxy has
  a writer addon for that; frida doesn't)

## What's here

| File | Role |
|---|---|
| `proxy_runtime.py` | `start_proxy()` — embeds `mitmproxy.DumpMaster` in local/WinDivert mode, hooks the parent's `proxy/addon.py::YiXianInterceptor` |
| `cert_setup.py` | Generates + installs the mitmproxy CA into Windows Trusted Root |
| `run_live.ps1` | Self-elevating PowerShell launcher (sets env vars + runs `app.py`) |
| `capture_game.bat` | Same idea, batch file |

## How to use

From the repo root:

```powershell
# Opt into the legacy proxy method
$env:YX_PROXY = "1"
.\.venv\Scripts\python.exe app.py
```

`app.py` notices `YX_PROXY=1`, adds this folder to `sys.path`, loads
`cert_setup` + `proxy_runtime.start_proxy`, and runs the consumer like
before. Requires admin (for WinDivert) and the mitmproxy CA in Trusted
Root (cert_setup handles that on first run).

## Why this was deprecated

Frida is simpler for end-users:

| | Proxy (this folder) | Frida (current default) |
|---|---|---|
| Admin / WinDivert | Required | Not needed |
| CA cert in Trusted Root | Required | Not needed |
| Bundled dependency size | mitmproxy (~50 MB) | frida (~42 MB) |
| Failure mode on game patch | Wire schema rename (rare) | `ProtobufParser` class rename (uncommon) |

The parsing pipeline downstream of `addon.process_msgpack` is **identical**
between the two — they only differ in where they intercept the bytes.
