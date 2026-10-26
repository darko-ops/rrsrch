"""Fetching a public web document for an agent, safely (docs/SOURCES.md, "Safety").

An agent names a URL; the engine fetches it. Since the engine runs inside a private network, a URL must not be able
to reach anything internal: only https on the standard port, only hosts whose every address is public, checked
before connecting and again for the address actually connected to (so a DNS answer that changes in between can't
slip past), at most 3 redirects, each checked the same way, a timeout on each read, a deadline for the whole fetch
(DEADLINE, redirects included) and a size cap (10 MB, or 50 MB for a PDF). Proxy settings in the environment are
ignored: the checks are only true of a direct connection.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

MAX_BYTES = 10 * 1024 * 1024             # HTML and plain text
PDF_MAX_BYTES = 50 * 1024 * 1024         # PDFs: annual reports and filings run large
TIMEOUT = 20.0                           # seconds for any one connect or read
DEADLINE = 120.0                         # seconds for the whole fetch: a 50 MB PDF at well under 1 MB/s
MAX_REDIRECTS = 3
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
PDF_TYPES = ("application/pdf", "application/x-pdf")
DOC_TYPES = TEXT_TYPES + PDF_TYPES             # what an agent can add by URL (docs/SOURCES.md)


class FetchRefused(Exception):
    """The URL can't or mustn't be fetched; the message says why, for the agent."""


@dataclass(frozen=True)
class Fetched:
    url: str                # where the document was finally fetched from, after redirects
    content_type: str       # e.g. text/html
    charset: str | None
    body: bytes


def canonical(url: str) -> str:
    """The form a URL is stored and compared in: https, lower-case host, no fragment, no default port."""
    try:
        u = urlsplit(url.strip())
    except ValueError as e:
        raise FetchRefused(f"not a URL: {e}") from e
    if u.scheme != "https":
        raise FetchRefused("only https URLs can be added")
    if not u.hostname:
        raise FetchRefused("the URL has no host")
    if u.username or u.password:
        raise FetchRefused("URLs with credentials can't be added")
    if u.port not in (None, 443):
        raise FetchRefused("only the standard https port (443) is allowed")
    return urlunsplit(("https", u.hostname.lower(), u.path or "/", u.query, ""))


def _public(ip: str) -> bool:
    a = ipaddress.ip_address(ip.split("%")[0])
    return a.is_global and not a.is_multicast


def check_host(host: str, resolve: Callable = socket.getaddrinfo) -> None:
    """Refuse a host unless every address it resolves to is public."""
    try:
        if not _public(host):
            raise FetchRefused(f"{host} is not a public address")
        return
    except ValueError:
        pass                                            # a name, not an address literal
    try:
        infos = resolve(host, 443, type=socket.SOCK_STREAM)
    except OSError as e:
        raise FetchRefused(f"{host} could not be resolved") from e
    addrs = {i[4][0] for i in infos}
    if not addrs or not all(_public(a) for a in addrs):
        raise FetchRefused(f"{host} resolves to an address that isn't public")


def _peer(response: httpx.Response) -> str | None:
    stream = response.extensions.get("network_stream")
    addr = stream.get_extra_info("server_addr") if stream is not None else None
    return addr[0] if addr else None


def fetch(url: str, *, user_agent: str, client: httpx.Client | None = None, resolve: Callable = socket.getaddrinfo,
          max_bytes: int = MAX_BYTES, types: tuple[str, ...] = TEXT_TYPES,
          pdf_max_bytes: int = PDF_MAX_BYTES, deadline: float = DEADLINE) -> Fetched:
    """Fetch a public document. Raises FetchRefused with a reason an agent can act on."""
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False, trust_env=False)
    end = time.monotonic() + deadline

    def in_time() -> None:
        if time.monotonic() > end:
            raise FetchRefused(f"fetching the document took longer than {deadline:.0f} seconds")

    try:
        current = canonical(url)
        for _ in range(MAX_REDIRECTS + 1):
            in_time()
            check_host(urlsplit(current).hostname, resolve)
            try:
                with client.stream("GET", current, headers={"User-Agent": user_agent, "Accept": ", ".join(types)}) as r:
                    peer = _peer(r)
                    if peer is not None and not _public(peer):
                        raise FetchRefused("the server's address isn't public")
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        current = canonical(urljoin(current, r.headers["location"]))
                        continue
                    if r.status_code != 200:
                        raise FetchRefused(f"the server answered {r.status_code}")
                    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    if ctype not in types:
                        raise FetchRefused(f"{ctype or 'unknown content'} can't be stored: HTML, plain text and PDF can")
                    cap = pdf_max_bytes if ctype in PDF_TYPES else max_bytes
                    declared = r.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > cap:
                        raise FetchRefused(f"the document is larger than {cap // (1024 * 1024)} MB")
                    body = bytearray()
                    for chunk in r.iter_bytes():
                        in_time()
                        body += chunk
                        if len(body) > cap:
                            raise FetchRefused(f"the document is larger than {cap // (1024 * 1024)} MB")
                    return Fetched(current, ctype, r.charset_encoding, bytes(body))
            except httpx.HTTPError as e:
                raise FetchRefused(f"could not fetch the URL: {type(e).__name__}") from e
        raise FetchRefused(f"more than {MAX_REDIRECTS} redirects")
    finally:
        if own:
            client.close()
