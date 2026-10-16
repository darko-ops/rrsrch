"""PDFs as sources (docs/SOURCES.md, step 3): the same bytes give the same text, in an isolated reader."""
import psycopg
import pdfminer
import pytest
from test_agent_sources import fake_web  # noqa: F401  (a fixture)
from test_trust_db import PILOT, open_mr, world  # noqa: F401  (world is a fixture)

from rrsrch.corpus import pdf
from rrsrch.knowledge import ingest


def make_pdf(pages: list[list[tuple[int, str]]], title: str | None = None) -> bytes:
    """A small, valid PDF: each page a list of (font size, line) drawn top-down in Helvetica; a line that is only
    digits is a page number, in the bottom margin."""
    objs: list[bytes] = []
    n_pages = len(pages)
    font = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, lines in enumerate(pages):
        stream, y = [], 760
        for size, text in lines:
            esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            at = 40 if text.isdigit() else y                # a page number sits in the bottom margin
            stream.append(f"BT /F1 {size} Tf 72 {at} Td ({esc}) Tj ET")
            y -= size + 40 if size > 14 else size + 4
        body = "\n".join(stream).encode("latin-1")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode())
        objs.append(b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    info = None
    if title:
        objs.append(f"<< /Title ({title}) >>".encode("latin-1"))
        info = len(objs)
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for k, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    trailer = f"<< /Size {len(objs) + 1} /Root 1 0 R" + (f" /Info {info} 0 R" if info else "") + " >>"
    out += f"trailer\n{trailer}\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


SENTENCE = "Capital expenditures were 8.4 billion dollars in fiscal 2024, up from 7.7 billion a year earlier."
FILING = make_pdf([
    [(22, "Micron Technology Annual Report"), (10, "Liquidity and capital resources"), (10, SENTENCE),
     (10, "Operating cash flow covered the investment in full during the year."), (9, "1")],
    [(10, "Risk factors"), (10, "Demand for memory products is cyclical and can fall sharply in a downturn."),
     (10, "Our results depend on the pricing of DRAM and NAND products in the market."), (9, "2")],
])


def test_the_pinned_extractor_is_the_one_installed():
    assert pdfminer.__version__ == pdf.PDFMINER_VERSION and pdf.PDFMINER_VERSION in pdf.VERSION


def test_a_pdf_becomes_the_same_text_every_time():
    title, body = pdf.to_text(FILING)
    assert title == "Micron Technology Annual Report"                      # page 1's largest type
    assert SENTENCE in body and "Risk factors" in body
    assert "\n\n1\n\n" not in body and not body.endswith("2")               # bare page numbers are dropped
    assert body.index("Liquidity") < body.index("Risk factors")             # pages in order
    assert pdf.to_text(FILING) == (title, body)                             # a second, separate process agrees


def test_metadata_title_wins_and_text_is_normalised_only_as_described():
    assert pdf.to_text(make_pdf([[(10, "x " * 120)]], title="Annual Report 2024"))[0] == "Annual Report 2024"
    assert pdf._block("e\ufb03cient \ufb02ow-\u00ad\nbased co\u00ad\noperation") == "efficient flow-based cooperation"
    assert pdf._block("a well-\nknown result\n  across   lines") == "a well-known result across lines"
    assert pdf._block("8 -\n9") == "8 - 9"                                  # only a word's hyphen joins


def test_what_cant_be_cited_is_refused():
    with pytest.raises(pdf.PDFRefused, match="not a PDF"):
        pdf.to_text(b"<html>no</html>")
    with pytest.raises(pdf.PDFRefused, match="not a readable PDF|couldn't be read"):
        pdf.to_text(b"%PDF-1.7\n garbage that is not a PDF")
    with pytest.raises(pdf.PDFRefused, match="no text layer"):
        pdf.to_text(make_pdf([[(10, "Figure 1")]]))                        # a scan has (almost) no text


def test_long_pdfs_are_refused_not_cut_short(monkeypatch):
    monkeypatch.setattr(pdf, "MAX_PAGES", 1)
    with pytest.raises(pdf.PDFRefused, match="more than 1 pages"):
        pdf.extract(FILING)


def test_agents_bring_a_pdf_by_url_and_cite_it(world, fake_web, monkeypatch):
    client_, h, url = world
    pages, seen = fake_web
    monkeypatch.setattr(ingest.web, "fetch", lambda u, *, user_agent, types, **_: (
        seen.append(types) or ingest.web.Fetched(u, "application/pdf", None, FILING)))
    r = client_.post("/v1/sources", headers=h["bot"], json={"url": "https://example.com/report.pdf"})
    assert r.status_code == 201, r.json()
    src = r.json()["source"]
    assert "application/pdf" in seen[-1] and src["title"] == "Micron Technology Annual Report"
    span = client_.get(f"/v1/sources/{src['id']}/locate", params={"quote": SENTENCE}).json()["spans"][0]
    content = {"repository": PILOT, "type": "empirical", "proposition": "Micron's fiscal 2024 capex was $8.4 billion.",
               "evidence": [["supports", {k: span[k] for k in ("source_id", "doc_sha256", "start", "end")}]]}
    mr = open_mr(client_, h["bot"], {"repository": PILOT, "content": content})
    checks = {c["name"]: c["passed"] for c in client_.get(f"/v1/merge-requests/{mr}").json()["checks"]}
    assert checks["sources_known"]
    with psycopg.connect(url) as c:
        detail = c.execute("SELECT detail FROM audit_events WHERE action = 'source.add'").fetchone()[0]
    assert detail["converter"] == pdf.VERSION and detail["content_type"] == "application/pdf"


def test_a_scanned_pdf_is_refused_with_a_reason(world, monkeypatch):
    client_, h, url = world
    monkeypatch.setattr(ingest.web, "fetch", lambda u, **_: ingest.web.Fetched(
        u, "application/pdf", None, make_pdf([[(10, "Scan")]])))
    r = client_.post("/v1/sources", headers=h["bot"], json={"url": "https://example.com/scan.pdf"})
    assert r.status_code == 422 and "text layer" in r.json()["error"]


def test_a_pdf_can_be_uploaded(world):
    import base64
    client_, h, url = world
    r = client_.post("/v1/sources/upload", headers=h["bot"], json={
        "content_base64": base64.b64encode(FILING).decode(), "content_type": "application/pdf",
        "origin": "Micron's 2024 annual report, from the company's investor site, downloaded 2026-10-16"})
    assert r.status_code == 201, r.json()
    assert r.json()["source"]["provenance"] == "uploaded"


def test_pdfs_get_a_larger_size_cap_than_web_pages():
    from test_agent_sources import client, resolver
    from rrsrch.sources import web
    r = resolver({"example.com": ["93.184.216.34"]})
    big_pdf = client({"https://example.com/r.pdf": (200, {"content-type": "application/pdf"}, FILING)})
    got = web.fetch("https://example.com/r.pdf", user_agent="t", client=big_pdf, resolve=r, types=web.DOC_TYPES,
                    max_bytes=100, pdf_max_bytes=len(FILING))            # over the page cap, within the PDF cap
    assert got.body == FILING
    with pytest.raises(web.FetchRefused, match="larger than"):
        web.fetch("https://example.com/r.pdf", user_agent="t", client=big_pdf, resolve=r, types=web.DOC_TYPES,
                  pdf_max_bytes=len(FILING) - 1)
    assert (web.MAX_BYTES, web.PDF_MAX_BYTES) == (10 * 1024 ** 2, 50 * 1024 ** 2)


def test_uploads_are_capped_by_type(world, monkeypatch):
    import base64
    client_, h, url = world
    monkeypatch.setattr(ingest.web, "MAX_BYTES", 1000)                   # pages and text: tiny for the test
    body = lambda content, ctype: {"content_base64": base64.b64encode(content).decode(), "content_type": ctype,
                                   "origin": "a test document made for this check, 2026-10-16"}
    r = client_.post("/v1/sources/upload", headers=h["bot"], json=body(b"<p>" + b"x" * 2000 + b"</p>", "text/html"))
    assert r.status_code == 422 and "1 MB" not in r.json()["error"] and "text/html" in r.json()["error"]
    r = client_.post("/v1/sources/upload", headers=h["bot"], json=body(FILING, "application/pdf"))
    assert r.status_code == 201, r.json()                               # a PDF of the same size or more is fine
