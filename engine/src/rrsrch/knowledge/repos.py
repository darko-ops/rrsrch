"""Creating and changing repositories. Every change is audited.

Only an admin of the owning organization creates a repository; changing one
needs its owner role (which org admins have). New rules are a new policy
version; old versions stay, since merge requests and verification runs name
the version they were judged under.

Public repositories (docs/REPOSITORIES.md). A person who admins an organization creates one, or makes one public.
So may an agent of the organization whose key carries the `administer` scope (which only an admin of the
organization can grant it), if:

  - its organization is claimed (not unclaimed agents or site people) and isn't RRSRCH itself (RRSRCH's own public
    repositories are opened by a person)
  - its organization has opened fewer than AGENT_PUBLIC_PER_30D public repositories this way in the last 30 days
  - the policy keeps independent review: at least one approval, and only from other organizations. Otherwise an
    agent could open a public repository whose claims show as supported with nobody else having looked.

A repository of an organization RRSRCH hasn't verified is public and works like any other, but is shown as an
"unverified operator" repository, and its claims stay out of Knowledge Health and search answers until RRSRCH
verifies the organization: anyone can open an organization, so its claims aren't counted as the network's
knowledge yet. An agent that creates a repository becomes its owner.

The same review floor holds whenever an agent changes a public repository's policy. The repository records that
an agent created it.
"""
from __future__ import annotations

import psycopg

from ..identity import access, onboarding
from ..identity import store as ids
from ..identity.access import Action, Principal
from ..trust import audit, disclosure, features
from ..trust.merge import Refused
from ..trust.policy import Policy
from ..trust.policy import load as load_policy


AGENT_PUBLIC_PER_30D = 3


def _human(conn, p: Principal) -> bool:
    return conn.execute("SELECT kind FROM agents WHERE id = %s", (p.agent_id,)).fetchone()[0] == "human"


def _review_floor(policy: Policy) -> None:
    if policy.required_approvals < 1 or not policy.approvals_from_other_orgs_only:
        raise Refused(403, "a public repository an agent runs keeps independent review: set required_approvals to at "
                           "least 1 and approvals_from_other_orgs_only to true")


def _agent_may_publish(conn, p: Principal, org: str, policy: Policy) -> None:
    """Refuse unless this agent may make a repository of `org` public (see the module docstring)."""
    if org == "rrsrch":
        raise Refused(403, "RRSRCH's own public repositories are opened by a person")
    recent = conn.execute("SELECT count(*) FROM repositories WHERE organization_id = %s AND created_via = 'agent' "
                          "AND visibility = 'public' AND created_at > now() - interval '30 days'", (org,)).fetchone()[0]
    if recent >= AGENT_PUBLIC_PER_30D:
        raise Refused(429, f"{org}'s agents have opened {recent} public repositories in the last 30 days (the limit is "
                           f"{AGENT_PUBLIC_PER_30D}); try again later, or ask a person who admins it")
    _review_floor(policy)


def create(conn: psycopg.Connection, p: Principal | None, slug: str, topic: str, description: str,
           visibility: str, rules: dict) -> int:
    org = slug.split("/", 1)[0]
    if p is None:
        raise Refused(401, "authentication required")
    if p.status != "active":
        raise Refused(403, f"agent is {p.status}")
    if "administer" not in p.scopes:
        raise Refused(403, "key lacks the 'administer' scope (an admin of your organization can issue you one)")
    if p.organization_id != org:
        raise Refused(403, f"only {org}'s own agents and admins can create its repositories")
    if onboarding.is_unvetted(org):
        raise Refused(403, "repositories belong to an organization: get claimed by an operator first")
    if ids.get_repo(conn, slug):
        raise Refused(409, f"{slug} already exists")
    policy = Policy.model_validate(rules)
    human = _human(conn, p)
    if visibility == "public" and not human:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"repo-create:{org}",))   # the limit, exactly
        _agent_may_publish(conn, p, org, policy)
    features.check_policy(p, policy, visibility)
    via = "human" if human else "agent"
    repo_id = conn.execute(
        "INSERT INTO repositories (slug, organization_id, topic, description, visibility, policy_version, created_by, "
        "created_via) VALUES (%s, %s, %s, %s, %s, 'v1', %s, %s) RETURNING id",
        (slug, org, topic, description, visibility, p.agent_id, via)).fetchone()[0]
    conn.execute("INSERT INTO policies (repository_id, version, rules, created_by) VALUES (%s, 'v1', %s, %s)",
                 (repo_id, policy.model_dump_json(), p.agent_id))
    if p.org_role != "admin":                           # an agent that opened it runs it (org admins own it already)
        ids.set_member(conn, repo_id, p.agent_id, "owner", granted_by=None)
    audit.append(conn, "repository.create", f"repo:{slug}", actor_id=p.agent_id, repository_id=repo_id,
                 policy_version="v1", detail={"visibility": visibility, "created_via": via,
                                              "rules": policy.model_dump(mode="json")})
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
    human = _human(conn, p)
    public_after = (visibility or repo.visibility) == "public"
    if not human and public_after and (rules is not None or repo.visibility != "public"):
        # an agent publishing a repository, or changing a public one's rules: the same conditions as creating one
        current = conn.execute("SELECT policy_version FROM repositories WHERE id = %s", (repo.id,)).fetchone()[0]
        next_policy = Policy.model_validate(rules) if rules is not None else load_policy(conn, repo.id, current)
        if repo.visibility != "public":
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"repo-create:{repo.organization_id}",))
            _agent_may_publish(conn, p, repo.organization_id, next_policy)
        else:
            _review_floor(next_policy)
    if visibility == "public" and repo.visibility != "public":
        # publishing waits for disclosure: the lock orders this against an embargo being set at the same moment
        conn.execute("SELECT 1 FROM repositories WHERE id = %s FOR UPDATE", (repo.id,))
        held = disclosure.embargoed_in(conn, repo.id)
        if held:
            raise Refused(409, f"{len(held)} claim(s) are under embargo, the last until {max(u for _, u in held):%Y-%m-%d}: "
                               f"claims {', '.join(str(c) for c, _ in held[:20])}. Lift the embargoes (or wait for "
                               "their dates) before making the repository public")
    # making a repository private is always allowed: hiding is never what the switch guards against
    if rules is not None or (visibility is not None and visibility != repo.visibility and visibility != "private"):
        # the security switch: what the policy will be, at the visibility it will have
        current = conn.execute("SELECT policy_version FROM repositories WHERE id = %s", (repo.id,)).fetchone()[0]
        effective = Policy.model_validate(rules) if rules is not None else load_policy(conn, repo.id, current)
        features.check_policy(p, effective, visibility or repo.visibility)
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
