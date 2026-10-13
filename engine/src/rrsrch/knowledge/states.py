"""Claim review states (SPEC-v2 §7.3) and the moves allowed between them.

A state says where a claim is in review and what support it has, not whether
it is true: a supported claim can become contested. Rejected, superseded and
retracted are final; a corrected claim is a new revision or a new claim.
"""
from __future__ import annotations

from enum import StrEnum


class ClaimState(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    STRUCTURALLY_VALID = "structurally_valid"
    UNDER_REVIEW = "under_review"
    SUPPORTED = "supported"
    CONTESTED = "contested"
    REJECTED = "rejected"
    STALE = "stale"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


S = ClaimState
TRANSITIONS: dict[ClaimState, frozenset[ClaimState]] = {
    S.DRAFT: frozenset({S.SUBMITTED}),
    S.SUBMITTED: frozenset({S.STRUCTURALLY_VALID, S.REJECTED}),
    S.STRUCTURALLY_VALID: frozenset({S.UNDER_REVIEW, S.REJECTED, S.SUPERSEDED, S.RETRACTED}),
    S.UNDER_REVIEW: frozenset({S.SUPPORTED, S.CONTESTED, S.REJECTED}),
    S.SUPPORTED: frozenset({S.CONTESTED, S.STALE, S.SUPERSEDED, S.RETRACTED}),
    S.CONTESTED: frozenset({S.UNDER_REVIEW, S.SUPPORTED, S.REJECTED, S.SUPERSEDED, S.RETRACTED}),
    S.STALE: frozenset({S.UNDER_REVIEW, S.SUPERSEDED, S.RETRACTED}),
    S.REJECTED: frozenset(),
    S.SUPERSEDED: frozenset(),
    S.RETRACTED: frozenset(),
}
FINAL = frozenset(s for s, nxt in TRANSITIONS.items() if not nxt)


class IllegalTransition(ValueError):
    pass


def check(current: ClaimState | str, to: ClaimState | str) -> ClaimState:
    """The target state, if moving there from `current` is allowed."""
    cur, nxt = ClaimState(current), ClaimState(to)
    if nxt not in TRANSITIONS[cur]:
        raise IllegalTransition(f"{cur} -> {nxt} is not allowed")
    return nxt
