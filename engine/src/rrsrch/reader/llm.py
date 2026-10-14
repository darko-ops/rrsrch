"""The model the reader runs on: any OpenAI-compatible chat endpoint.

vLLM and Ollama on the DGX Spark both serve this API, so the reader doesn't
care which. Configure with:

  RRSRCH_LLM_URL       e.g. http://spark-31f4.local:8000/v1   (vLLM)
                            http://spark-31f4.local:11434/v1  (Ollama)
  RRSRCH_READER_MODEL  the model name the server knows it by
  RRSRCH_LLM_TIMEOUT   seconds to wait for one model call (default 300); raise it
                       for a large model on slow hardware
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import httpx


DEFAULT_TIMEOUT = 300.0


@dataclass
class LLM:
    base_url: str
    model: str
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> "LLM":
        url, model = os.environ.get("RRSRCH_LLM_URL"), os.environ.get("RRSRCH_READER_MODEL")
        if not url or not model:
            raise RuntimeError("set RRSRCH_LLM_URL and RRSRCH_READER_MODEL (see rrsrch/reader/llm.py)")
        raw = os.environ.get("RRSRCH_LLM_TIMEOUT", "").strip()
        try:
            timeout = float(raw) if raw else DEFAULT_TIMEOUT
        except ValueError:
            timeout = 0.0
        if not 0 < timeout < float("inf"):
            raise RuntimeError(f"RRSRCH_LLM_TIMEOUT must be a positive number of seconds, not {raw!r}")
        return cls(url.rstrip("/"), model, timeout)

    def json_chat(self, system: str, user: str) -> dict:
        """One deterministic (temperature 0) call that must return a JSON object."""
        r = httpx.post(f"{self.base_url}/chat/completions", timeout=self.timeout, json={
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"] or ""
        return parse_json_object(content)


def parse_json_object(content: str) -> dict:
    """The first JSON object in a reply, tolerating a ```json fence around it."""
    content = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", content.strip())
    start = content.find("{")
    if start < 0:
        raise ValueError("reply has no JSON object")
    obj, _ = json.JSONDecoder().raw_decode(content[start:])
    if not isinstance(obj, dict):
        raise ValueError("reply is not a JSON object")
    return obj
