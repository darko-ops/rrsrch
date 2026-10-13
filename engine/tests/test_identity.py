"""Keys and the access decision, without a database."""
import pytest

from rrsrch.identity import access, keys
from rrsrch.identity.access import Action, Principal, Repo, Role

PUBLIC = Repo(1, "rrsrch/msc-knee-oa", "rrsrch", "public")
PRIVATE = Repo(2, "acme/internal", "acme", "private")
ALL = frozenset(access.SCOPES)


def agent(org="rrsrch", org_role="member", status="active", scopes=ALL):
    return Principal(agent_id=9, handle="a", organization_id=org, org_role=org_role, status=status, scopes=scopes)


def test_keys_round_trip_and_reject_lookalikes():
    token, prefix, h = keys.generate()
    assert keys.parse(token) == (prefix, token.split("_", 2)[2])
    assert keys.matches(token.split("_", 2)[2], h) and not keys.matches("x" * 43, h)
    assert keys.generate()[0] != token
    for bad in ("", "rrsrch_", token + "x", token.replace("rrsrch_", "other_"), f"rrsrch_{prefix.upper()}_{'a' * 43}"):
        assert keys.parse(bad) is None


def test_anyone_reads_public_but_nothing_else_without_a_key():
    assert access.decide(None, Action.READ, PUBLIC, None)
    d = access.decide(None, Action.PROPOSE, PUBLIC, None)
    assert not d and d.reason == "authentication required"
    assert not access.decide(None, Action.READ, PRIVATE, None)


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("action", list(Action))
def test_roles_are_ranked(role, action):
    allowed = access.decide(agent(), action, PRIVATE, role).allowed
    assert allowed == (role.rank >= access.NEEDS[action].rank)


def test_scopes_and_status_narrow_what_a_role_allows():
    owner = Role.OWNER
    assert not access.decide(agent(scopes=frozenset({"read"})), Action.PROPOSE, PRIVATE, owner)
    assert access.decide(agent(scopes=frozenset({"read"})), Action.READ, PRIVATE, owner)
    for status in ("suspended", "revoked"):
        d = access.decide(agent(status=status), Action.READ, PRIVATE, owner)
        assert not d and status in d.reason
    assert not access.decide(agent(), Action.READ, PRIVATE, None)          # no role, no access


def test_org_admins_own_their_org_repositories_only():
    admin = agent(org="acme", org_role="admin")
    assert access.decide(admin, Action.ADMINISTER, PRIVATE, None)
    assert not access.decide(agent(org="rrsrch", org_role="admin"), Action.READ, PRIVATE, None)
    assert access.can_manage_agents(admin, "acme")
    assert not access.can_manage_agents(admin, "rrsrch")
    assert not access.can_manage_agents(agent(org="acme"), "acme")          # members can't
    assert not access.can_manage_agents(agent(org="acme", org_role="admin", scopes=frozenset({"read"})), "acme")
