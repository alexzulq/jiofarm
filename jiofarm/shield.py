"""JioFarm — DNS-over-HTTPS shield for GrizzlySMS API.

Monkey-patches ``socket.getaddrinfo`` so the GrizzlySMS hostname is always
resolved through Cloudflare DoH, bypassing ISP-level DNS hijacking.
"""

from __future__ import annotations

import json
import socket
import urllib.request

_DOH_CACHE: dict[str, str] = {}
_PROTECTED_HOSTS = {"api.grizzlysms.com", "5sim.net"}


def _doh_resolve(host: str) -> str | None:
    if host in _DOH_CACHE:
        return _DOH_CACHE[host]
    try:
        req = urllib.request.Request(
            f"https://1.1.1.1/dns-query?name={host}&type=A",
            headers={"accept": "application/dns-json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            for ans in json.loads(r.read().decode()).get("Answer", []):
                if ans.get("type") == 1:
                    _DOH_CACHE[host] = ans["data"]
                    return _DOH_CACHE[host]
    except Exception:
        pass
    return None


def install_doh_shield() -> None:
    """Patch socket.getaddrinfo to resolve protected SMS hosts via DoH."""
    orig = socket.getaddrinfo

    def patched(host, port, *a, **kw):
        if host in _PROTECTED_HOSTS:
            ip = _doh_resolve(host)
            if ip:
                return orig(ip, port, *a, **kw)
        return orig(host, port, *a, **kw)

    socket.getaddrinfo = patched