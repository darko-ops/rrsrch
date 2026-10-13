"""API keys: `rrsrch_<prefix>_<secret>`.

The prefix is public and looks the key up; only a sha256 of the secret is
stored. The secret is 256 random bits, so a fast hash is enough: there is
nothing to brute-force that a slow hash would protect.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

_TOKEN = re.compile(r"^rrsrch_([0-9a-f]{12})_([A-Za-z0-9_-]{43})$")


def generate() -> tuple[str, str, str]:
    """A new key: (token to hand out once, prefix, secret hash to store)."""
    prefix, secret = secrets.token_hex(6), secrets.token_urlsafe(32)
    return f"rrsrch_{prefix}_{secret}", prefix, hash_secret(secret)


def parse(token: str) -> tuple[str, str] | None:
    m = _TOKEN.match(token)
    return (m.group(1), m.group(2)) if m else None


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def matches(secret: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), stored_hash)
