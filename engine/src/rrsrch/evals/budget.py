"""Budgets enforced by the harness, not requested of the model (SPEC-v2 §19.3).

Every tool call goes through a Meter, which counts it, records what it did
(for the duplication and unauthorized-action metrics) and stops the agent the
moment its budget is spent. Conditions get identical budgets.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    pass


@dataclass(frozen=True)
class Budget:
    max_tool_calls: int = 30
    max_tokens: int = 60_000          # model tokens, prompt + completion, as the model server reports them


@dataclass
class Call:
    tool: str
    key: str                          # what was touched, for duplication: e.g. read:MED:1/abstract
    status: int                       # HTTP-like: 200 ok, 4xx refused, 0 harness error


@dataclass
class Meter:
    budget: Budget
    calls: list[Call] = field(default_factory=list)
    tokens: int = 0
    exhausted: str | None = None
    error: str | None = None          # the turn ended on a model or harness error

    def charge_call(self) -> None:
        if len(self.calls) >= self.budget.max_tool_calls:
            self.exhausted = "tool_calls"
            raise BudgetExceeded(f"tool-call budget of {self.budget.max_tool_calls} spent")

    def record(self, tool: str, key: str, status: int) -> None:
        self.calls.append(Call(tool, key, status))

    def charge_tokens(self, n: int) -> None:
        self.tokens += n
        if self.tokens > self.budget.max_tokens:
            self.exhausted = "tokens"
            raise BudgetExceeded(f"token budget of {self.budget.max_tokens} spent")
