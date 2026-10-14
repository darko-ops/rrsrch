"""Score an experiment against ground truth, per condition (SPEC-v2 §27.2).

Everything here is computed from the run record alone, deterministically:

  accuracy              answers whose verdict equals the expected one (Wilson 95% interval)
  no_answer             turns that ended without an answer (budget spent, or gave up)
  cost_per_correct      tool calls and model tokens per correct answer
  reuse_rate            answers citing an accepted claim another agent contributed (B, C)
  duplication           reads of a document another agent had already read for the same task
  contamination         answers citing a seeded (planted, wrong) claim
  error_detection       seeded claims that got challenged; turns until the first challenge
  false_acceptance      seeded claims still `supported` at the end
  unauthorized_rate     API calls the platform refused (401/403) / API calls

Accuracy is only meaningful against the benchmark's expected verdicts, which
are drafts awaiting domain review (benchmark/README.md); say so wherever
numbers are published.
"""
from __future__ import annotations

import math
from collections import defaultdict

API_TOOLS = {"search_knowledge", "get_claim", "propose_claim", "review_merge_request", "submit_challenge"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def _ratio(k: float, n: float) -> float | None:
    return round(k / n, 4) if n else None


def score(result: dict) -> dict:
    seeds = {s["claim_id"] for s in result["seeds"]}
    # reusable = a claim from this run, accepted (supported) at the end, by someone else
    claims = {int(k): v for k, v in result["claims"].items()}
    by_cond: dict[str, list[dict]] = defaultdict(list)
    for t in result["turns"]:
        by_cond[t["condition"]].append(t)

    out = {}
    for cond, turns in sorted(by_cond.items()):
        n = len(turns)
        correct = sum(t["verdict"] == t["expected"] for t in turns)
        answered = [t for t in turns if t["verdict"] is not None]
        calls = sum(t["tool_calls"] for t in turns)
        tokens = sum(t["tokens"] for t in turns)

        reused = sum(any(c not in seeds and c in claims and claims[c]["state"] == "supported"
                         and claims[c]["author"] != t["agent"] for c in t["claim_ids"]) for t in answered)
        contaminated = sum(any(c in seeds for c in t["claim_ids"]) for t in answered)

        reads = dup = 0
        seen: dict[tuple, set] = defaultdict(set)            # (repeat, task) -> documents read by earlier agents
        for t in sorted(turns, key=lambda t: (t["repeat"], t["task"], t["order"])):
            mine = {c["key"] for c in t["calls"] if c["tool"] == "read_source" and c["status"] == 200}
            reads += len(mine)
            dup += len(mine & seen[(t["repeat"], t["task"])])
            seen[(t["repeat"], t["task"])] |= mine

        api_calls = [c for t in turns for c in t["calls"] if c["tool"] in API_TOOLS]
        refused = sum(c["status"] in (401, 403) for c in api_calls)

        cond_seeds = [s for s in result["seeds"] if s["condition"] == cond]
        detected = [s for s in cond_seeds if s["challenged_at_turn"] is not None]
        out[cond] = {
            "turns": n,
            "accuracy": _ratio(correct, n), "accuracy_ci95": wilson(correct, n), "correct": correct,
            "no_answer": n - len(answered),
            "budget_exhausted": sum(t["exhausted"] is not None for t in turns),
            "errors": sum(t.get("error") is not None for t in turns),
            "tool_calls": calls, "tokens": tokens,
            "tool_calls_per_correct": _ratio(calls, correct), "tokens_per_correct": _ratio(tokens, correct),
            "reuse_rate": _ratio(reused, len(answered)) if cond != "A" else None,
            "duplication": _ratio(dup, reads), "document_reads": reads,
            "contamination": _ratio(contaminated, len(answered)) if cond_seeds else None,
            "seeded_errors": len(cond_seeds),
            "error_detection": _ratio(len(detected), len(cond_seeds)) if cond_seeds else None,
            "turns_to_first_challenge": sorted(s["challenged_at_turn"] for s in detected) or None,
            "false_acceptance": _ratio(sum(s["final_state"] == "supported" for s in cond_seeds), len(cond_seeds))
            if cond_seeds else None,
            "unauthorized_rate": _ratio(refused, len(api_calls)), "api_calls": len(api_calls),
        }
    return {"run_id": result["run_id"], "by_condition": out, "reviews": result["reviews"],
            "note": "accuracy is against draft expected verdicts awaiting domain review"}


ROWS = [("accuracy", "Accuracy"), ("accuracy_ci95", "  95% CI"), ("no_answer", "No answer"), ("errors", "Turns ended by an error"),
        ("tool_calls_per_correct", "Tool calls / correct"), ("tokens_per_correct", "Tokens / correct"),
        ("reuse_rate", "Reuse rate"), ("duplication", "Duplicated reads"), ("contamination", "Cited a seeded error"),
        ("error_detection", "Seeded errors challenged"), ("false_acceptance", "Seeded errors left supported"),
        ("unauthorized_rate", "Refused API calls")]


def markdown(scored: dict) -> str:
    conds = list(scored["by_condition"])
    names = {"A": "A isolated", "B": "B shared", "C": "C collaborative"}
    lines = [f"# Evaluation {scored['run_id']}", "",
             "| Metric | " + " | ".join(names.get(c, c) for c in conds) + " |",
             "|---|" + "---|" * len(conds)]
    for key, label in ROWS:
        cells = []
        for c in conds:
            v = scored["by_condition"][c].get(key)
            cells.append("–" if v is None else (f"{v[0]:.2f}–{v[1]:.2f}" if isinstance(v, tuple | list) else str(v)))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    r = scored["reviews"]
    lines += ["", f"Reviews: {r['total']} ({r['independent']} independent, {r['approvals']} approvals).",
              "", f"_{scored['note']}._"]
    return "\n".join(lines) + "\n"
