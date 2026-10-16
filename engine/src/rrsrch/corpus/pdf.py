"""PDFs as text a claim can point into (docs/SOURCES.md, step 3).

Claims cite character offsets, so the same PDF bytes must always give the same string, on every machine. That is
why the extractor is pdfminer.six, which is pure Python (no platform-specific build to differ), pinned to an exact
version, with every layout parameter set here rather than left to the library's defaults. The converter's version
names the library version, and is recorded with each stored document.

What the text looks like:
  - pages in order; on each page, pdfminer's text boxes in its reading order, each box one block
  - blocks separated by a blank line; a line ending in a hyphen joins the next with no space ("well-" + "known"),
    other line breaks become a space; whitespace is collapsed
  - typographic ligatures (fi, fl, ...) are spelled out and soft hyphens dropped, so quotes match what people type;
    nothing else is normalised
  - blocks that are only a page number are dropped

A PDF is untrusted input that can be built to exhaust a parser, so extraction runs in a child process with a time
limit and a memory cap, and stops after MAX_PAGES pages. Encrypted PDFs and PDFs with no text layer (scans) are
refused: there is nothing exact to cite.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

PDFMINER_VERSION = "20260107"           # must match the pin in pyproject.toml
VERSION = f"pdf-v1+pdfminer.six-{PDFMINER_VERSION}"
MAX_PAGES = 500
MAX_CHARS = 5_000_000
TIMEOUT = 90                            # seconds
MEMORY = 2 * 1024 ** 3                  # bytes of address space for the child (where the OS supports the limit)
MIN_TEXT = 200                          # fewer characters than this: no usable text layer

_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st",
              "ﬆ": "st", "­": "", " ": " "}
_LIG = re.compile("|".join(_LIGATURES))
_WS = re.compile(r"\s+")
_PAGE_NUMBER = re.compile(r"^(?:page\s+)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?$", re.I)


class PDFRefused(Exception):
    """The PDF can't be turned into citable text; the message says why."""


def _params():
    from pdfminer.layout import LAParams
    return LAParams(line_overlap=0.5, char_margin=2.0, line_margin=0.5, word_margin=0.1, boxes_flow=0.5,
                    detect_vertical=False, all_texts=False)


def _block(raw: str) -> str:
    raw = raw.replace("\u00ad\n", "")                  # a soft hyphen at a line break joins the word back up
    lines = [_WS.sub(" ", _LIG.sub(lambda m: _LIGATURES[m.group(0)], ln)).strip() for ln in raw.splitlines()]
    out = ""
    for ln in (x for x in lines if x):
        if not out:
            out = ln
        elif out.endswith("-") and len(out) > 1 and out[-2].isalpha():
            out += ln                                   # "well-" + "known" -> "well-known"
        else:
            out += " " + ln
    return out


_WORDY = re.compile(r"[^\W\d_]{3,}")


def _looks_like_title(b: str) -> bool:
    """A first block worth calling the title: a few real words, not a margin stamp or a page header of digits."""
    return len(b) <= 300 and len(_WORDY.findall(b)) >= 3


def _title(meta: dict) -> str:
    from pdfminer.utils import decode_text     # PDF text strings: UTF-16 with a byte-order mark, else PDFDocEncoding
    raw = meta.get("Title")
    if isinstance(raw, bytes):
        raw = decode_text(raw)
    title = _WS.sub(" ", str(raw or "")).strip()
    if len(title) < 4 or title.lower() in ("untitled", "microsoft word") or re.search(r"\.(docx?|pdf|indd)$", title, re.I):
        return ""
    return title[:500]


def extract(data: bytes) -> tuple[str, str]:
    """(title, body). Runs in this process: callers should use to_text, which isolates it."""
    from io import BytesIO

    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer
    from pdfminer.pdfdocument import PDFDocument, PDFEncryptionError, PDFPasswordIncorrect
    from pdfminer.pdfparser import PDFParser, PDFSyntaxError

    try:
        doc = PDFDocument(PDFParser(BytesIO(data)))
    except (PDFEncryptionError, PDFPasswordIncorrect) as e:
        raise PDFRefused("the PDF is encrypted") from e
    except PDFSyntaxError as e:
        raise PDFRefused("not a readable PDF") from e
    if doc.encryption is not None:
        raise PDFRefused("the PDF is encrypted")
    meta = {}
    for info in doc.info or []:
        meta.update({k: v for k, v in info.items() if isinstance(v, (bytes, str))})
    blocks: list[str] = []
    size = 0
    first_page: list[tuple[float, str]] = []           # (largest font size, block) on page 1, for the title
    for n, page in enumerate(extract_pages(BytesIO(data), laparams=_params(), maxpages=MAX_PAGES + 1), 1):
        if n > MAX_PAGES:
            raise PDFRefused(f"the PDF has more than {MAX_PAGES} pages")
        for el in page:
            if isinstance(el, LTTextContainer):
                b = _block(el.get_text())
                if b and not _PAGE_NUMBER.match(b):
                    blocks.append(b)
                    size += len(b) + 2
                    if n == 1:
                        first_page.append((_font_size(el), b))
        if size > MAX_CHARS:
            raise PDFRefused(f"the PDF has more than {MAX_CHARS:,} characters of text")
    body = "\n\n".join(blocks)
    if len(body) < MIN_TEXT:
        raise PDFRefused("the PDF has no text layer to cite (a scan?); only PDFs with real text can be stored")
    # the title: the document's own metadata, else page 1's largest type that reads like words, else the first such block
    big = max((fs for fs, b in first_page if _looks_like_title(b)), default=0)
    title = (_title(meta) or next((b for fs, b in first_page if fs == big and _looks_like_title(b)), "")
             or next((b for b in blocks if _looks_like_title(b)), ""))[:500]
    return title, body


def _font_size(box) -> float:
    """The largest character size in a text box, rounded so tiny rendering differences can't change the choice."""
    from pdfminer.layout import LTChar
    sizes = [round(ch.size, 1) for line in box for ch in line if isinstance(ch, LTChar)]
    return max(sizes, default=0.0)


def _limit_memory() -> None:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
    except (ImportError, ValueError, OSError):
        pass                                            # not every OS supports it; the timeout still applies


def to_text(data: bytes) -> tuple[str, str]:
    """(title, body) of a PDF, extracted in an isolated child process. Raises PDFRefused."""
    if not data.startswith(b"%PDF-"):
        raise PDFRefused("not a PDF")
    try:
        done = subprocess.run([sys.executable, "-m", "rrsrch.corpus.pdf"], input=data, capture_output=True,
                              timeout=TIMEOUT, env={"PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
                                                    "PATH": os.environ.get("PATH", "")})
    except subprocess.TimeoutExpired as e:
        raise PDFRefused(f"reading the PDF took longer than {TIMEOUT} seconds") from e
    try:
        out = json.loads(done.stdout or b"{}")
    except ValueError:
        out = {}
    if "error" in out:
        raise PDFRefused(out["error"])
    if done.returncode != 0 or "body" not in out:
        raise PDFRefused("the PDF couldn't be read")
    return out["title"], out["body"]


def _main() -> int:
    _limit_memory()                                     # set in the child itself: safe, unlike preexec_fn in a server
    data = sys.stdin.buffer.read()
    try:
        title, body = extract(data)
        sys.stdout.write(json.dumps({"title": title, "body": body}))
    except PDFRefused as e:
        sys.stdout.write(json.dumps({"error": str(e)}))
    except MemoryError:
        sys.stdout.write(json.dumps({"error": "reading the PDF needed too much memory"}))
    except Exception as e:  # noqa: BLE001  (a malformed PDF can fail anywhere in the parser)
        sys.stdout.write(json.dumps({"error": f"the PDF couldn't be read ({type(e).__name__})"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
