"""
cert_setup.py — make the mitmproxy CA trusted automatically.

The proxy MITMs the game's TLS, so its CA must be in the Windows "Trusted Root
Certification Authorities" store; otherwise the game's connection fails and
nothing decodes. This module, called once at startup (the exe is built with
--uac-admin so it already runs elevated), will:

  1. generate the mitmproxy CA if it doesn't exist yet (fresh machine),
  2. check whether THAT CA is already in the LocalMachine Root store,
  3. install it via certutil if not.

Idempotent and silent (no console windows). Returns a short status string.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CONFDIR = Path.home() / ".mitmproxy"
CER = CONFDIR / "mitmproxy-ca-cert.cer"


def _no_window():
    """STARTUPINFO that hides the certutil console window (Windows only)."""
    if not sys.platform.startswith("win"):
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si


def _run(args):
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="ignore",
        startupinfo=_no_window(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _generate_ca() -> bool:
    """Create the mitmproxy CA files under ~/.mitmproxy (idempotent)."""
    try:
        from mitmproxy.certs import CertStore
        CONFDIR.mkdir(parents=True, exist_ok=True)
        CertStore.from_store(CONFDIR, "mitmproxy", 2048)
        return CER.exists()
    except Exception:
        return False


def _thumbprint() -> str | None:
    """SHA-1 fingerprint of the local CA cert (hex), or None."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        data = CER.read_bytes()
        try:
            cert = x509.load_der_x509_certificate(data)
        except Exception:
            cert = x509.load_pem_x509_certificate(data)
        return cert.fingerprint(hashes.SHA1()).hex()
    except Exception:
        return None


def _is_trusted(thumb: str) -> bool:
    """True if a cert with this thumbprint is in the LocalMachine Root store."""
    if not thumb:
        return False
    r = _run(["certutil", "-verifystore", "Root", thumb])
    return r.returncode == 0


def _install() -> bool:
    """Add the CA to LocalMachine Root (needs elevation, which --uac-admin gives)."""
    r = _run(["certutil", "-addstore", "-f", "Root", str(CER)])
    return r.returncode == 0


def ensure_cert_trusted(log=lambda *a: None) -> str:
    """Generate + trust the mitmproxy CA if needed. Returns a status string."""
    if not sys.platform.startswith("win"):
        return "skip (not windows)"
    if not CER.exists():
        log("[cert] generating mitmproxy CA …")
        if not _generate_ca():
            return "error: could not generate CA"
    thumb = _thumbprint()
    if _is_trusted(thumb):
        return "ok (already trusted)"
    log("[cert] installing mitmproxy CA into Trusted Root …")
    if _install():
        # verify it took
        return "installed" if _is_trusted(thumb) else "installed (unverified)"
    return "error: install failed (not elevated?)"


if __name__ == "__main__":
    print(ensure_cert_trusted(print))
