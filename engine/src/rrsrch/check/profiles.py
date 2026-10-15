"""Domain profiles: what the citation gate reads text with, per repository (docs/security/PLAN.md §5.1).

A repository's policy names its profile (`Policy.profile`). A profile is the vocabulary (entity and scope groups,
and the file they come from), the extractor that turns text into the fields the gate compares (numbers, findings,
entities, scope), which entity groups a claim inherits from its source, and the population a report is about by
default.

`clinical` is the behaviour the gate had before profiles existed, unchanged; it is the default. A security
profile (package, ecosystem, advisory, versions) arrives with its vocabulary in phase 2; until then a policy that
names it is refused, rather than silently checked with the clinical rules.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from . import fields, vocab


@dataclass(frozen=True)
class Profile:
    name: str
    vocab: vocab.Vocabulary
    extract: Callable[[str], fields.Fields]
    # what a claim inherits from its source when its own text is silent (see gate._effective)
    inherited: tuple[str, ...] = ()
    # the population a report is about, when the caller doesn't say
    report_scope: dict[str, str] = field(default_factory=dict)


CLINICAL = Profile(
    name="clinical",
    vocab=vocab.CLINICAL,
    extract=fields.extract,
    # the population, and the intervention ("the cell-recipient group improved" is a claim about MSCs because the
    # study is). Outcomes are never inherited: a claim must name what it measured.
    inherited=("species", "joint", "condition", "cell_type"),
    report_scope={"species": "human", "joint": "knee", "condition": "osteoarthritis"},
)

PROFILES: dict[str, Profile] = {CLINICAL.name: CLINICAL}


def get(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown evidence profile {name!r} (available: {', '.join(sorted(PROFILES))})") from None
