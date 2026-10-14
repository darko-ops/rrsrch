"""Review requests: asking a particular agent to review a merge request (SPEC-v2 §8.2).

The author or a maintainer asks; the reviewer must be able to review in that
repository and can't be the author. A request is done when the reviewer
reviews (rrsrch.trust.merge.review closes it), or declined by the reviewer.
"""
from __future__ import annotations

import psycopg

from ..identity import access
from ..identity import store as ids
from ..identity.access import Action, Principal, Role
from ..trust import audit
from ..trust.merge import Refused, repo_and_role, require


def request(conn: psycopg.Connection, p: Principal | None, mr_id: int, reviewer: str) -> int:
    mr = conn.execute("SELECT repository_id, author_id, state FROM merge_requests WHERE id = %s", (mr_id,)).fetchone()
    if mr is None:
        raise Refused(404, "not found")
    repo_id, author_id, state = mr
    if p is None or p.agent_id != author_id:
        require(conn, p, Action.MAINTAIN, repo_id)
    else:
        require(conn, p, Action.PROPOSE, repo_id)
    if state != "open":
        raise Refused(409, f"merge request is {state}")
    agent = ids.get_agent(conn, reviewer)
    if agent is None or agent["status"] != "active":
        raise Refused(404 if agent is None else 409, f"no active agent {reviewer}")
    if agent["id"] == author_id:
        raise Refused(409, "the author can't review their own change")
    repo, _ = repo_and_role(conn, None, repo_id)
    as_reviewer = access.Principal(agent["id"], agent["handle"], agent["organization_id"], agent["org_role"],
                                   agent["status"], frozenset())
    role = access.effective_role(as_reviewer, repo, ids.role_in(conn, agent["id"], repo_id))
    if role is None or role.rank < Role.REVIEWER.rank:
        raise Refused(409, f"{reviewer} can't review in {repo.slug} (needs the reviewer role)")
    row = conn.execute("INSERT INTO review_requests (merge_request_id, requested_by, reviewer_id) VALUES (%s, %s, %s) "
                       "ON CONFLICT (merge_request_id, reviewer_id) DO NOTHING RETURNING id",
                       (mr_id, p.agent_id, agent["id"])).fetchone()
    if row is None:
        raise Refused(409, f"{reviewer} was already asked")
    audit.append(conn, "review_request.open", f"mr:{mr_id}", actor_id=p.agent_id, repository_id=repo_id,
                 detail={"review_request_id": row[0], "reviewer": reviewer})
    return row[0]


def decline(conn: psycopg.Connection, p: Principal | None, request_id: int) -> None:
    row = conn.execute("SELECT r.merge_request_id, r.reviewer_id, r.state, m.repository_id FROM review_requests r "
                       "JOIN merge_requests m ON m.id = r.merge_request_id WHERE r.id = %s", (request_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    mr_id, reviewer_id, state, repo_id = row
    if p is None or p.agent_id != reviewer_id:
        raise Refused(403, "only the requested reviewer can decline")
    if state != "open":
        raise Refused(409, f"review request is {state}")
    conn.execute("UPDATE review_requests SET state = 'declined', closed_at = now() WHERE id = %s", (request_id,))
    audit.append(conn, "review_request.decline", f"mr:{mr_id}", actor_id=p.agent_id, repository_id=repo_id,
                 detail={"review_request_id": request_id})


def mine(conn: psycopg.Connection, p: Principal) -> list[dict]:
    cols = ("id", "merge_request_id", "repository", "requested_by", "created_at")
    return [dict(zip(cols, r)) for r in conn.execute(
        "SELECT r.id, r.merge_request_id, rp.slug, a.handle, r.created_at FROM review_requests r "
        "JOIN merge_requests m ON m.id = r.merge_request_id JOIN repositories rp ON rp.id = m.repository_id "
        "JOIN agents a ON a.id = r.requested_by WHERE r.reviewer_id = %s AND r.state = 'open' ORDER BY r.id",
        (p.agent_id,))]
