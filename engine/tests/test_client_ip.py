"""The client address the per-IP limits see for a direct caller through Tailscale Funnel (serve/api.py SERVER)."""
import asyncio

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from rrsrch.serve import api


def client_seen(peer: str, forwarded: str | None) -> str:
    seen = {}

    async def app(scope, receive, send):
        seen["host"] = scope["client"][0]

    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    scope = {"type": "http", "scheme": "http", "client": (peer, 5000), "headers": headers}
    asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=api.SERVER["forwarded_allow_ips"])(scope, None, None))
    return seen["host"]


def test_funnel_passes_the_callers_address():
    assert api.SERVER["proxy_headers"] is True
    assert client_seen("127.0.0.1", "206.85.204.43") == "206.85.204.43"


def test_a_forged_forwarded_header_changes_nothing():
    # Funnel appends the real address after whatever the caller sent; the last one wins
    assert client_seen("127.0.0.1", "203.0.113.77, 206.85.204.43") == "206.85.204.43"


def test_only_loopback_is_trusted_to_forward():
    assert client_seen("198.51.100.9", "203.0.113.77") == "198.51.100.9"
