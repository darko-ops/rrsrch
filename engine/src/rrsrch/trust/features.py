"""The security-domain switch (docs/security/PLAN.md): the phase-0 machinery ships dark until the findings it would
carry have been independently reviewed.

  RRSRCH_SECURITY_FEATURES = off        (default) no policy may use them; commit evidence is refused everywhere
                           = operator   only admins of the network org, in private repositories, for testing
                           = on         available to every repository (the public security launch)

"Them" are: commit (git_ref) evidence, claim kinds and per-kind overrides, and any profile but clinical. A policy that
already uses them keeps loading whatever the switch says; the switch decides what can be saved and what is accepted.
"""
from __future__ import annotations

import os

from ..identity.access import Principal, can_operate_network
from .policy import Policy

MODES = ("off", "operator", "on")


def mode() -> str:
    m = os.environ.get("RRSRCH_SECURITY_FEATURES", "off").strip().lower()
    return m if m in MODES else "off"


def uses_security(policy: Policy) -> bool:
    return ("git_ref" in policy.allowed_evidence or bool(policy.kinds) or bool(policy.overrides)
            or policy.profile != "clinical")


def check_policy(p: Principal | None, policy: Policy, visibility: str) -> None:
    """Refuse saving a policy that uses the security features unless the switch allows it here."""
    from .merge import Refused        # here, not at the top: merge imports the pipeline, which imports this module
    if not uses_security(policy):
        return
    m = mode()
    if m == "on":
        return
    if m == "operator" and can_operate_network(p) and visibility == "private":
        return
    raise Refused(403, "security features (commit evidence, claim kinds, overrides, non-clinical profiles) aren't "
                       "enabled on this server" + (": in testing, only network operators may use them, in private "
                                                   "repositories" if m == "operator" else ""))


def commit_evidence_enabled() -> bool:
    return mode() != "off"
