"""Find a model's quote in the document, exactly, or reject it.

The reader asks the model to copy each claim's supporting passage verbatim.
Models drift in typography (curly vs straight quotes, dash widths, spacing), so
those are normalized on both sides. Nothing else is: a quote with a changed
word, number or letter case is not in the document, and the claim is rejected.
That is what stops a model from inventing a passage to cite.
"""
from __future__ import annotations

import threading
from array import array
from collections import OrderedDict
from collections.abc import Callable

_TRANSLATE = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
}


def _normalize(text: str) -> tuple[str, list[int]]:
    """Normalized text plus, for each of its characters, the offset it came from."""
    out: list[str] = []
    origin: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        ch = _TRANSLATE.get(ch, ch)
        if ch.isspace():
            if prev_space:
                continue
            ch, prev_space = " ", True
        else:
            prev_space = False
        out.append(ch)
        origin.append(i)
    return "".join(out), origin


def locate(quote: str, text: str, start: int = 0, end: int | None = None) -> tuple[int, int] | None:
    """(start, end) offsets of quote in text[start:end], or None if it isn't there verbatim."""
    t, origin = _normalize(text[start:end])
    hit = _find(quote, t, origin)
    return None if hit is None else (start + hit[0], start + hit[1])


def _find(quote: str, t: str, origin) -> tuple[int, int] | None:
    q, _ = _normalize(quote.strip())
    if len(q) < 12:
        return None                          # too short to pin a claim to
    pos = t.find(q)
    if pos < 0:
        return None
    return origin[pos], origin[pos + len(q) - 1] + 1


class Normalized:
    """Whole documents normalized once and kept, newest used first, up to `budget` characters in all, so looking up
    quotes in the same document again doesn't redo the work. The caller's key names the text (a stored document's
    id and hash: its text never changes under them). At most `at_once` documents are normalized at the same time."""

    def __init__(self, budget: int = 20_000_000, at_once: int = 2):
        self.budget = budget
        self.kept: OrderedDict[str, tuple[str, array]] = OrderedDict()
        self.lock = threading.Lock()
        self.working = threading.BoundedSemaphore(at_once)

    def get(self, key: str, text: Callable[[], str]) -> tuple[str, array]:
        with self.lock:
            if key in self.kept:
                self.kept.move_to_end(key)
                return self.kept[key]
        with self.working:
            with self.lock:                                 # another request may have done it meanwhile
                if key in self.kept:
                    return self.kept[key]
            t, origin = _normalize(text())
            got = (t, array("I", origin))
        with self.lock:
            self.kept[key] = got
            while sum(len(v[0]) for v in self.kept.values()) > self.budget and len(self.kept) > 1:
                self.kept.popitem(last=False)
        return got

    def clear(self) -> None:
        with self.lock:
            self.kept.clear()

    def locate(self, quote: str, key: str, text: Callable[[], str]) -> tuple[int, int] | None:
        """locate(quote, text), for a whole document known by `key`."""
        return _find(quote, *self.get(key, text))
