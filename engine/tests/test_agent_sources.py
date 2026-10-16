"""Agents bring sources (docs/SOURCES.md): safe fetching, deterministic text, provenance, and repositories choosing."""
import socket

import httpx
import psycopg
import pytest
from test_trust_db import PILOT, open_mr, world  # noqa: F401  (world is a fixture)

from rrsrch.corpus import html as htmlmod
from rrsrch.knowledge import ingest
from rrsrch.sources import web

PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def resolver(table):
    def resolve(host, port, type=None):
        if host not in table:
            raise OSError("no such host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in table[host]]
    return resolve


def client(routes):
    def handler(req: httpx.Request):
        status, headers, body = routes[str(req.url)]
        return httpx.Response(status, headers=headers, content=body)
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


# --- the fetcher ---------------------------------------------------------------------------------------------------

def test_only_public_https_urls_are_fetched():
    for bad, why in [("http://example.com/a", "only https"), ("https://example.com:8443/a", "standard https port"),
                     ("https://u:p@example.com/", "credentials"), ("ftp://x/", "only https")]:
        with pytest.raises(web.FetchRefused, match=why):
            web.canonical(bad)
    assert web.canonical("https://Example.COM/a?b=1#frag") == "https://example.com/a?b=1"
    for host in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "192.168.7.25", "100.64.0.1"):
        with pytest.raises(web.FetchRefused, match="not a public address"):
            web.check_host(host)
    with pytest.raises(web.FetchRefused, match="isn't public"):
        web.check_host("intranet.example", resolver({"intranet.example": ["93.184.216.34", "10.1.1.1"]}))
    web.check_host("example.com", resolver({"example.com": ["93.184.216.34"]}))


def test_redirects_are_checked_and_only_text_is_taken():
    r = resolver({"example.com": ["93.184.216.34"], "internal.example": ["10.0.0.2"]})
    hop = client({"https://example.com/a": (302, {"location": "https://internal.example/secret"}, b"")})
    with pytest.raises(web.FetchRefused, match="isn't public"):
        web.fetch("https://example.com/a", user_agent="t", client=hop, resolve=r)
    pdf = client({"https://example.com/a.pdf": (200, {"content-type": "application/pdf"}, b"%PDF")})
    with pytest.raises(web.FetchRefused, match="can.t be stored"):      # (text-only callers; sources take PDFs)
        web.fetch("https://example.com/a.pdf", user_agent="t", client=pdf, resolve=r)
    big = client({"https://example.com/big": (200, {"content-type": "text/html"}, b"x" * 2000)})
    with pytest.raises(web.FetchRefused, match="larger than"):
        web.fetch("https://example.com/big", user_agent="t", client=big, resolve=r, max_bytes=1000)
    ok = client({"https://example.com/a": (301, {"location": "/b"}, b""),
                 "https://example.com/b": (200, {"content-type": "text/html; charset=utf-8"}, b"<p>hi</p>")})
    got = web.fetch("https://example.com/a", user_agent="t", client=ok, resolve=r)
    assert (got.url, got.content_type, got.charset, got.body) == ("https://example.com/b", "text/html", "utf-8", b"<p>hi</p>")


# --- text ----------------------------------------------------------------------------------------------------------

FILING = """<html><head><title>Micron Technology 10-K</title><style>p{}</style></head><body>
<div style="display:none"><ix:header><div>hidden fact</div></ix:header></div><nav>Home | Filings</nav>
<h2>Liquidity</h2><p>Capital expenditures   were $8.4 billion
in fiscal 2024.</p>
<table><tr><th>(in millions)</th><th>2024</th><th>2023</th></tr>
<tr><td>Revenue</td><td>$25,111</td><td>$15,540</td></tr>
<tr><td>Expenditures for property, plant, and equipment</td><td>(8,386)</td><td>(7,676)</td></tr></table>
</body></html>"""


def test_html_becomes_the_same_text_every_time():
    title, body = htmlmod.to_text(FILING)
    assert title == "Micron Technology 10-K"
    assert body == ("Liquidity\n\nCapital expenditures were $8.4 billion in fiscal 2024.\n\n"
                    "(in millions) | 2024 | 2023\n\nRevenue | $25,111 | $15,540\n\n"
                    "Expenditures for property, plant, and equipment | (8,386) | (7,676)")
    assert htmlmod.to_text(FILING) == (title, body)
    assert "hidden fact" not in body and "Home" not in body


# --- adding a source by URL ----------------------------------------------------------------------------------------

@pytest.fixture
def fake_web(monkeypatch):
    pages, seen = {}, []

    def fetch(url, *, user_agent, **_):
        seen.append((url, user_agent))
        if url not in pages:
            raise web.FetchRefused("the server answered 404")
        return web.Fetched(url, "text/html", "utf-8", pages[url])
    monkeypatch.setattr(ingest.web, "fetch", fetch)
    return pages, seen


SEC_URL = "https://www.sec.gov/Archives/edgar/data/723125/000072312524000027/mu-20240829.htm"
QUOTE = "Capital expenditures were $8.4 billion in fiscal 2024."


def test_agents_bring_a_web_document_and_cite_it(world, fake_web):
    client_, h, url = world
    pages, seen = fake_web
    pages["https://example.com/report"] = FILING.encode()
    assert client_.post("/v1/sources", json={"url": "https://example.com/report"}).status_code == 401
    assert client_.post("/v1/sources", headers=h["bot"], json={"url": "http://example.com/report"}).status_code == 400
    assert client_.post("/v1/sources", headers=h["bot"], json={"url": "https://example.com/missing"}).status_code == 422
    two = client_.post("/v1/sources", headers=h["bot"], json={"url": "https://example.com/x", "doi": "10.1/x"})
    assert two.status_code == 400

    r = client_.post("/v1/sources", headers=h["bot"], json={"url": "https://Example.com/report#top"})
    assert r.status_code == 201, r.json()
    src = r.json()["source"]
    assert src["id"].startswith("URL:") and (src["kind"], src["provenance"]) == ("url", "fetched")
    assert (src["url"], src["added_by"], src["title"]) == ("https://example.com/report", "bot", "Micron Technology 10-K")
    again = client_.post("/v1/sources", headers=h["bot"], json={"url": "https://example.com/report"})
    assert again.status_code == 200 and again.json()["source"]["id"] == src["id"] and len(seen) == 2

    span = client_.get(f"/v1/sources/{src['id']}/locate", params={"quote": QUOTE}).json()["spans"][0]
    content = {"repository": PILOT, "type": "empirical", "proposition": "Micron's fiscal 2024 capex was $8.4 billion.",
               "evidence": [["supports", {k: span[k] for k in ("source_id", "doc_sha256", "start", "end")}]]}
    mr = open_mr(client_, h["bot"], {"repository": PILOT, "content": content})
    checks = {c["name"]: c["passed"] for c in client_.get(f"/v1/merge-requests/{mr}").json()["checks"]}
    assert checks["sources_known"] and checks["source_provenance"]
    with psycopg.connect(url) as c:
        detail = c.execute("SELECT detail FROM audit_events WHERE action = 'source.add'").fetchone()[0]
    assert detail["kind"] == "url" and len(detail["content_sha256"]) == 64 and detail["converter"] == htmlmod.VERSION


def test_sec_filings_get_a_readable_id_and_the_sec_user_agent(world, fake_web):
    client_, h, url = world
    pages, seen = fake_web
    pages[SEC_URL] = FILING.encode()
    src = client_.post("/v1/sources", headers=h["bot"], json={"url": SEC_URL}).json()["source"]
    assert src["id"] == "SEC:0000723125-24-000027:mu-20240829.htm"
    assert (src["kind"], src["provenance"]) == ("sec", "registry")
    assert seen[-1][1] == ingest.SEC_USER_AGENT
    assert client_.get(f"/v1/sources/{src['id']}").json()["source"]["url"] == SEC_URL


def test_a_repository_decides_which_provenance_it_accepts(world, fake_web):
    client_, h, url = world
    pages, _ = fake_web
    pages["https://example.com/report"] = FILING.encode()
    src = client_.post("/v1/sources", headers=h["bot"], json={"url": "https://example.com/report"}).json()["source"]
    r = client_.patch(f"/v1/repos/{PILOT}", headers=h["admin"], json={"policy": {"accepted_sources": ["registry"]}})
    assert r.status_code == 200, r.json()
    span = client_.get(f"/v1/sources/{src['id']}/locate", params={"quote": QUOTE}).json()["spans"][0]
    content = {"repository": PILOT, "type": "empirical", "proposition": "Micron's fiscal 2024 capex was $8.4 billion.",
               "evidence": [["supports", {k: span[k] for k in ("source_id", "doc_sha256", "start", "end")}]]}
    mr = open_mr(client_, h["bot"], {"repository": PILOT, "content": content})
    check = next(c for c in client_.get(f"/v1/merge-requests/{mr}").json()["checks"] if c["name"] == "source_provenance")
    assert check["passed"] is False and "accepts registry" in check["detail"]


# --- uploads (step 2) ----------------------------------------------------------------------------------------------

def upload(client_, who, content=FILING.encode(), ctype="text/html", origin="Micron FY2024 annual report, from the "
           "company's investor relations site, downloaded 2026-10-16", **kw):
    import base64
    return client_.post("/v1/sources/upload", headers=who, json={"content_base64": base64.b64encode(content).decode(),
                                                                  "content_type": ctype, "origin": origin} | kw)


def test_an_agent_can_upload_what_has_no_public_address_as_agent_supplied(world):
    client_, h, url = world
    assert upload(client_, {}).status_code == 401
    assert upload(client_, h["bot"], origin="short").status_code == 400          # origin says too little
    assert upload(client_, h["bot"], ctype="application/pdf").status_code == 422
    assert upload(client_, h["bot"], content=b"<p>hi</p>").status_code == 422    # nothing worth citing
    r = upload(client_, h["bot"])
    assert r.status_code == 201, r.json()
    src = r.json()["source"]
    assert src["id"].startswith("UP:") and (src["kind"], src["provenance"], src["url"]) == ("upload", "uploaded", None)
    assert src["origin"].startswith("Micron FY2024 annual report") and src["added_by"] == "bot"
    assert upload(client_, h["ext"]).json()["source"]["id"] == src["id"]       # same bytes, same source

    # the pilot doesn't accept uploads unless it opts in
    span = client_.get(f"/v1/sources/{src['id']}/locate", params={"quote": QUOTE}).json()["spans"][0]
    content = {"repository": PILOT, "type": "empirical", "proposition": "Micron's fiscal 2024 capex was $8.4 billion.",
               "evidence": [["supports", {k: span[k] for k in ("source_id", "doc_sha256", "start", "end")}]]}
    mr = open_mr(client_, h["bot"], {"repository": PILOT, "content": content})
    check = next(c for c in client_.get(f"/v1/merge-requests/{mr}").json()["checks"] if c["name"] == "source_provenance")
    assert check["passed"] is False
    assert client_.patch(f"/v1/repos/{PILOT}", headers=h["admin"],
                         json={"policy": {"accepted_sources": ["registry", "fetched", "uploaded"]}}).status_code == 200
    mr2 = open_mr(client_, h["bot"], {"repository": PILOT, "content": content | {"proposition": "Capex was $8.4B in FY2024."}})
    check = next(c for c in client_.get(f"/v1/merge-requests/{mr2}").json()["checks"] if c["name"] == "source_provenance")
    assert check["passed"] is True

    # a finding citing it shows readers it's agent-supplied, and where it came from
    pid = client_.post("/v1/posts", headers=h["bot"], json={"kind": "finding", "title": "Micron capex FY2024",
                                                             "body": "From its annual report.", "evidence": [
                                                                 {k: span[k] for k in ("source_id", "doc_sha256", "start", "end")}]}).json()["post_id"]
    ev = client_.get(f"/v1/posts/{pid}").json()["post"]["evidence"][0]
    assert (ev["source_provenance"], ev["source_url"]) == ("uploaded", None) and ev["source_origin"].startswith("Micron")
