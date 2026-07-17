from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class CiCap:
    outcome: str
    n: int
    target: str


@dataclass(frozen=True)
class StepDef:
    owner: Optional[str] = None
    routes: dict = field(default_factory=dict)
    pr_merge: Optional[str] = None
    pr_close: Optional[str] = None
    pr_feedback: Optional[str] = None
    pr_conflict: Optional[str] = None
    pr_conflict_cap: Optional[int] = None
    pr_conflict_escalate: Optional[str] = None
    mention_token: Optional[str] = None
    review_bot_allowlist: frozenset = frozenset()
    ci_cap: Optional[CiCap] = None
    workspace: Optional[str] = None
    hooks: frozenset = frozenset()
