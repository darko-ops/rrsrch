"""Web documents as text a claim can point into (docs/SOURCES.md, "Text conversion").

Claims cite character offsets, so this must be deterministic: the same bytes always give the same string. Nothing
here calls a model or the network.

Blocks (paragraphs, headings, list items, table rows, ...) each become one line of text, separated by blank lines,
in document order. A table row's cells are joined with " | ", because figures like capex and revenue live in
tables. Scripts, styles, navigation and inline XBRL's hidden header are left out. Whitespace inside a block is
collapsed to single spaces.
"""
from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

VERSION = "html-v1"

_BLOCK = {"p", "div", "section", "article", "header", "main", "aside", "blockquote", "pre", "li", "dt", "dd",
          "h1", "h2", "h3", "h4", "h5", "h6", "tr", "caption", "figcaption", "address", "table", "ul", "ol", "dl",
          "form", "fieldset", "center", "body"}
_CELL = {"td", "th"}
_SKIP = {"script", "style", "noscript", "template", "svg", "nav", "footer", "head", "iframe", "object", "ix:header"}
_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "param", "source", "track", "wbr"}
_WS = re.compile(r"\s+")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.buf: list[str] = []
        self.cells: list[str] | None = None        # inside a table row: its cells so far
        self.cell: list[str] | None = None
        self.skipping: list[str] = []               # tags open inside a skipped region; empty when reading
        self.title: list[str] = []
        self.in_title = False

    def _flush(self) -> None:
        text = _WS.sub(" ", "".join(self.buf)).strip()
        if text:
            self.blocks.append(text)
        self.buf = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
        if self.skipping:
            if tag not in _VOID:
                self.skipping.append(tag)
            return
        style = (dict(attrs).get("style") or "").replace(" ", "").lower()
        if tag in _SKIP or ("display:none" in style and tag not in _VOID):   # hidden content isn't read
            self.skipping = [tag]
            return
        if tag == "tr":
            self._flush()
            self.cells = []
        elif tag in _CELL and self.cells is not None:
            self.cell = []
        elif tag == "br":
            if self.cell is not None:
                self.cell.append(" ")
            else:
                self._flush()
        elif tag in _BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        if self.skipping:
            if tag in self.skipping:                    # close up to the matching tag (HTML is often unbalanced)
                while self.skipping and self.skipping.pop() != tag:
                    pass
            return
        if tag in _CELL and self.cell is not None and self.cells is not None:
            text = _WS.sub(" ", "".join(self.cell)).strip()
            if text:
                self.cells.append(text)
            self.cell = None
        elif tag == "tr" and self.cells is not None:
            if self.cells:
                self.blocks.append(" | ".join(self.cells))
            self.cells = None
        elif tag in _BLOCK:
            self._flush()

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        if self.skipping:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.cells is None:
            self.buf.append(data)                       # (stray text between a row's cells is dropped)


def to_text(html: str) -> tuple[str, str]:
    """(title, body text) of an HTML document."""
    p = _Text()
    p.feed(html)
    p.close()
    p._flush()
    title = _WS.sub(" ", unescape("".join(p.title))).strip()
    return title, "\n\n".join(p.blocks)


def plain(text: str) -> str:
    """Plain text with line endings normalised and trailing spaces trimmed; paragraphs kept."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def decode(body: bytes, charset: str | None) -> str:
    """Bytes as text: the declared charset, else UTF-8, replacing what doesn't decode (deterministically)."""
    for enc in (charset, "utf-8"):
        if enc:
            try:
                return body.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
    return body.decode("utf-8", errors="replace")
