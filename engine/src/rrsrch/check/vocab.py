"""Vocabularies, compiled for matching: the clinical one (vocab.yaml), and any other domain's (profiles.py).

Finding entities is deterministic: compiled patterns, first match wins within
a group, and matched text is masked so a later, looser pattern ("stem cells")
can't claim words a specific one ("bone marrow stem cells") already took.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

VOCAB_PATH = Path(__file__).with_name("vocab.yaml")

# Groups that describe what a claim is about vs. who it is about.
ENTITY_GROUPS = ("cell_type", "comparator", "outcome")
SCOPE_GROUPS = ("species", "joint", "condition")


@dataclass(frozen=True)
class Entity:
    group: str
    id: str
    parent: str | None
    pattern: re.Pattern


def _one(p: str) -> str:
    """One pattern, with its own case rule: abbreviations are case-sensitive."""
    letters = re.sub(r"[^A-Za-z]", "", p)
    sensitive = len(letters) >= 2 and letters[:2].isupper()
    return f"(?:{p})" if sensitive else f"(?i:{p})"


def _compile(patterns: list[str]) -> re.Pattern:
    return re.compile(rf"(?<![\w-])(?:{'|'.join(_one(p) for p in patterns)})(?![\w-])")


@lru_cache(maxsize=None)
def load(path: Path = VOCAB_PATH) -> dict[str, list[Entity]]:
    raw = yaml.safe_load(path.read_text())
    return {group: [Entity(group, e["id"], e.get("parent"),
                           _compile(e["patterns"]))
                    for e in entries]
            for group, entries in raw.items()}


@dataclass(frozen=True)
class Vocabulary:
    """One domain's vocabulary file and how its groups are used (see profiles.py). The module-level functions
    below are the clinical vocabulary's, for the code written before there was more than one."""
    path: Path
    entity_groups: tuple[str, ...]          # what a claim is about
    scope_groups: tuple[str, ...]           # who or what it is about
    # entity groups never read as scope ("Knee injury and Osteoarthritis Outcome Score" says nothing about who was
    # studied): masked out before a scope group is matched
    masks_scope: tuple[str, ...] = ()

    def entities(self, group: str) -> list[Entity]:
        return load(self.path)[group]

    def _mask_group(self, text: str, group: str) -> str:
        for e in self.entities(group):
            text = e.pattern.sub(lambda m: " " * len(m.group(0)), text)
        return text

    def find(self, text: str, group: str) -> frozenset[str]:
        """Entity ids of one group mentioned in text."""
        if group in self.scope_groups:
            for g in self.masks_scope:
                text = self._mask_group(text, g)
        found, masked = set(), text
        for e in self.entities(group):
            def take(m: re.Match) -> str:
                found.add(e.id)
                return " " * len(m.group(0))
            masked = e.pattern.sub(take, masked)
        return frozenset(found)

    def mask_all(self, text: str) -> str:
        """Text with every vocabulary term blanked out, so names like "T2 mapping" or "SF-36" are never read as
        numbers."""
        for group in load(self.path):
            text = self._mask_group(text, group)
        return text

    def ancestors(self, group: str, entity_id: str) -> list[str]:
        """[entity, parent, grandparent, ...] within a group."""
        by_id = {e.id: e for e in self.entities(group)}
        chain, cur = [], entity_id
        while cur and cur not in chain:
            chain.append(cur)
            cur = by_id[cur].parent if cur in by_id else None
        return chain


CLINICAL = Vocabulary(VOCAB_PATH, ENTITY_GROUPS, SCOPE_GROUPS, masks_scope=("outcome",))


def find(text: str, group: str) -> frozenset[str]:
    """Entity ids of one group mentioned in text.

    Population terms are never read out of an instrument's name: "Knee injury
    and Osteoarthritis Outcome Score" says nothing about who was studied.
    """
    return CLINICAL.find(text, group)


def mask_all(text: str) -> str:
    """Text with every vocabulary term blanked out, so names like "T2 mapping"
    or "SF-36" are never read as numbers."""
    return CLINICAL.mask_all(text)


def ancestors(group: str, entity_id: str) -> list[str]:
    """[entity, parent, grandparent, ...] within a group."""
    return CLINICAL.ancestors(group, entity_id)
