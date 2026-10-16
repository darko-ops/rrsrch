"""Test helpers for the one review endpoint (POST /v1/reviews, docs/SIMPLIFY.md): objections and reproduction or
usage reviews in the shapes the tests were written with."""

CHECK_VERDICT = {("reproduction", "reproduced"): "reproduced", ("reproduction", "failed"): "could_not_reproduce",
                 ("reproduction", "inconclusive"): "inconclusive",
                 ("reproduction", "insufficient_evidence"): "insufficient_evidence",
                 ("usage", "worked"): "worked", ("usage", "worked_with_conditions"): "worked_with_conditions",
                 ("usage", "failed"): "did_not_work", ("usage", "outdated"): "outdated",
                 ("usage", "missing_step"): "missing_step", ("usage", "unclear"): "unclear"}


def object_to(client, headers, claim_id, kind="other", statement="", blocking=True, evidence=None):
    """An objection to a claim (what was POST /v1/claims/N/challenges)."""
    return client.post("/v1/reviews", headers=headers, json={
        "target": f"claim:{claim_id}", "verdict": "object", "objection": kind, "findings": statement,
        "blocking": blocking, "evidence": evidence or []})


def as_review(d: dict) -> dict:
    """A report in the old shape ({target, context, outcome, observations, ...}) as a review body."""
    d = dict(d)
    verdict = CHECK_VERDICT.get((d.pop("context", None), d.pop("outcome", None)), "not-a-verdict")
    return {"target": d.pop("target", None), "verdict": verdict, "findings": d.pop("observations", ""), **d}


def report(client, headers, **body):
    """A reproduction or usage review (what was POST /v1/verifications)."""
    return client.post("/v1/reviews", headers=headers, json=as_review(body))


def reports(client, target, headers=None):
    """The reproduction and usage reviews of a target, newest first, in the report shape."""
    items = client.get("/v1/reviews", headers=headers or {}, params={"target": target}).json().get("items", [])
    back = {v: k for k, v in CHECK_VERDICT.items()}
    out = []
    for r in reversed(items):
        if r["kind"] in ("reproduction", "usage"):
            context, outcome = r["kind"], r["verdict"]
            out.append({"id": r["id"], "context": context, "outcome": outcome, "author": r["reviewer"],
                        "observations": r["findings"], **{k: r["details"].get(k) for k in
                        ("method", "environment", "conditions", "limitations", "versions", "artifacts")}})
    return out


def notes(client, headers):
    """The agent's notifications, oldest first, from its inbox (GET /v1/notifications went with step 3)."""
    items = client.get("/v1/inbox", headers=headers).json().get("items", [])
    return [i for i in reversed(items) if i["id"].startswith("event:")]


def submission(client, bounty_id, submission_id, headers=None):
    """One bounty submission, as the bounty lists it."""
    subs = client.get(f"/v1/bounties/{bounty_id}", headers=headers or {}).json()["bounty"]["submissions_detail"]
    return next(s for s in subs if s["id"] == submission_id)
