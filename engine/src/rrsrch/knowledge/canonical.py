"""Canonical JSON: the exact bytes a content hash is computed over.

Two artifacts with the same content must hash the same no matter how their
keys were ordered or which machine wrote them, so the encoding is pinned:
keys sorted, no insignificant whitespace, UTF-8 (not \\u escapes), and no
NaN or infinity, which JSON can't represent. Strings are hashed as given, with
no Unicode normalization: claim spans are character offsets into stored text,
and normalizing would change what they point at.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def dumps(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(obj: Any) -> str:
    return hashlib.sha256(dumps(obj)).hexdigest()
