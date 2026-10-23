"""Which model an agent runs, normalized so agents can be compared by model (docs/BENCHMARKS.md).

Agents report their own model as free text ("ollama/qwen3.8:27b-q4_K_M", "meta/muse-spark-1.3"), and nobody checks
it: every grouping by model says so. Normalizing drops the runtime that serves it (ollama/, openrouter/ ...) and the
local tag after ":" (size, quantization), keeps who made it as `provider`, and names a `family`: the alphabetic words
the name starts with, so qwen3.8 is qwen, llama-3.1-8b is llama, claude-opus-4 is claude-opus, deepseek-r1 is
deepseek.

Bot platforms that run one model are different: their agents report "grokbot/<the bot's own name>", so the part
after the slash names the bot, not the model. Those are listed as the platform itself (model grokbot, family grok,
by xai) unless the rest names a model of that family (grokbot/grok-4 is grok-4).
"""
from __future__ import annotations

import re

UNDISCLOSED = "undisclosed"
RUNTIMES = {"ollama", "lmstudio", "lm-studio", "vllm", "llamacpp", "llama.cpp", "llama-cpp", "mlx", "local",
            "openrouter", "together", "togetherai", "groq", "fireworks", "deepinfra", "bedrock", "vertex", "vertexai",
            "azure", "hf", "huggingface", "replicate", "litellm"}
PLATFORMS = {"grokbot": ("grok", "xai")}        # platform: (the family of the model it runs, who makes it)
_FAMILY = re.compile(r"[a-z]+(?:-[a-z]+(?=-|$))*")
_SAFE = re.compile(r"[^a-z0-9._/:-]")


def normalize(raw: str | None) -> dict:
    s = _SAFE.sub("", (raw or "").strip().lower())
    parts = [p for p in s.split("/") if p]
    if not parts:
        return {"model": UNDISCLOSED, "family": UNDISCLOSED, "provider": None, "runtime": None}
    if parts[0] in PLATFORMS:
        family, provider = PLATFORMS[parts[0]]
        named = parts[-1].split(":")[0] if len(parts) > 1 else ""
        return {"model": named[:80] if named.startswith(family) else parts[0], "family": family, "provider": provider,
                "runtime": parts[0]}
    runtime = parts.pop(0) if len(parts) > 1 and parts[0] in RUNTIMES else None
    provider = parts.pop(0) if len(parts) > 1 else None
    name = "/".join(parts).split(":")[0] or UNDISCLOSED
    fam = _FAMILY.match(name.rsplit("/", 1)[-1])
    return {"model": name[:80], "family": fam.group(0)[:40] if fam else name[:40], "provider": provider,
            "runtime": runtime}
