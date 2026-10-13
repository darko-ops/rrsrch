"""Creating and changing repositories. Every change is audited.

Only an admin of the owning organization creates a repository; changing one
needs its owner role (which org admins have). Public repositories are
created, or made public, only by a human admin: SPEC-v2 §9.4 keeps new public
repositories under human approval for now. New rules are a new policy
version; old versions stay, since merge requests and verification runs name
the version they were judged under.
"""
from __future__ import annotations

import psycopg

from ..identity import access
from ..identity import store as ids
from ..identity.access import Action, Principal
from ..trust import audit
from ..trust.merge import Refused
from ..trust.policy import Policy


def _human(conn, p: Principal) -> bool:
    return conn.execute("SELECT kind FROM agents WHERE id = %s", (p.agent_id,)).fetchone()[0] == "human"


def create(conn: psycopg.Connection, p: Principal | None, slug: str, topic: str, description: str,
           visibility: str, rules: dict) -> int:
    org = slug.split("/", 1)[0]
    if p is None:
        raise Refused(401, "authentication required")
    if p.status != "active":
        raise Refused(403, f"agent is {p.status}")
    if "administer" not in p.scopes:
        raise Refused(403, "key lacks the 'administer' scope")
    if p.org_role != "admin" or p.organization_id != org:
        raise Refused(403, f"only an admin of {org} can create its repositories")
    if visibility == "public" and not _human(conn, p):
        raise Refused(403, "public repositories are created by a human admin")
    if ids.get_repo(conn, slug):
        raise Refused(409, f"{slug} already exists")
    policy = Policy.model_validate(rules)
    repo_id = conn.execute(
        "INSERT INTO repositories (slug, organization_id, topic, description, visibility, policy_version) "
        "VALUES (%s, %s, %s, %s, %s, 'v1') RETURNING id", (slug, org, topic, description, visibility)).fetchone()[0]
    conn.execute("INSERT INTO policies (repository_id, version, rules, created_by) VALUES (%s, 'v1', %s, %s)",
                 (repo_id, policy.model_dump_json(), p.agent_id))
    audit.append(conn, "repository.create", f"repo:{slug}", actor_id=p.agent_id, repository_id=repo_id,
                 policy_version="v1", detail={"visibility": visibility, "rules": policy.model_dump(mode="json")})
    return repo_id


def update(conn: psycopg.Connection, p: Principal | None, slug: str, *, topic: str | None = None,
           description: str | None = None, visibility: str | None = None, rules: dict | None = None) -> str:
    """Change a repository; returns the policy version now in force."""
    repo = ids.get_repo(conn, slug)
    role = ids.role_in(conn, p.agent_id if p else None, repo.id) if repo else None
    if repo is None or not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")
    d = access.decide(p, Action.ADMINISTER, repo, role)
    if not d:
        raise Refused(401 if p is None else 403, d.reason)
    if visibility == "public" and repo.visibility != "public" and not _human(conn, p):
        raise Refused(403, "a repository is made public by a human")
    changes: dict = {k: v for k, v in (("topic", topic), ("description", description), ("visibility", visibility))
                     if v is not None}
    for col, val in changes.items():
        conn.execute(f"UPDATE repositories SET {col} = %s WHERE id = %s", (val, repo.id))
    version = conn.execute("SELECT policy_version FROM repositories WHERE id = %s", (repo.id,)).fetchone()[0]
    if rules is not None:
        policy = Policy.model_validate(rules)
        n = conn.execute("SELECT count(*) FROM policies WHERE repository_id = %s", (repo.id,)).fetchone()[0]
        while True:                      # next unused vN (seeded versions may have other names)
            n += 1
            version = f"v{n}"
            if not conn.execute("SELECT 1 FROM policies WHERE repository_id = %s AND version = %s",
                                (repo.id, version)).fetchone():
                break
        conn.execute("INSERT INTO policies (repository_id, version, rules, created_by) VALUES (%s, %s, %s, %s)",
                     (repo.id, version, policy.model_dump_json(), p.agent_id))
        conn.execute("UPDATE repositories SET policy_version = %s WHERE id = %s", (version, repo.id))
        changes["policy"] = {"version": version, "rules": policy.model_dump(mode="json")}
    audit.append(conn, "repository.update", f"repo:{slug}", actor_id=p.agent_id, repository_id=repo.id,
                 policy_version=version, detail=changes)
    return version
