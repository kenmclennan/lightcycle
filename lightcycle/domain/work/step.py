from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.domain.money import Cost
from lightcycle.domain.work.park import Park
from lightcycle.domain.work.state import State


@dataclass(frozen=True, slots=True)
class Step:
    id: str
    item: str
    title: str = ""
    stage: Optional[str] = None
    pass_id: Optional[str] = None
    role: Optional[str] = None
    state: State = State.QUEUED
    claimed_by: Optional[str] = None
    model: Optional[str] = None
    outcome: Optional[str] = None
    notes: Optional[str] = None
    reflection: Optional[str] = None
    watched_step: Optional[str] = None
    park: Park = field(default_factory=Park)
    deps: int = 0
    blocked_by: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    fired_at: Optional[str] = None
    closed_at: Optional[str] = None
    active_seconds: Optional[float] = None
    usage_input_tokens: int = 0
    usage_output_tokens: int = 0
    usage_cache_read_tokens: int = 0
    usage_cache_creation_tokens: int = 0
    usage_cost_usd: Cost = field(default_factory=Cost)
    usage_cost_basis: Optional[str] = None
    usage_thinking_tokens: Optional[int] = None
    turn_count: int = 0

    @property
    def type(self):
        return "step"

    @property
    def needs(self):
        return self.park.needs

    def classify_for_human(self, flow):
        sd = flow.step_def(self.stage)
        outs = sorted(sd.routes.keys())
        owner = sd.owner
        if owner is None or owner == "human":
            return ("action", outs)
        return ("blocked", outs + ["unblock"])

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "item": self.item,
            "title": self.title,
            "stage": self.stage,
            "pass": self.pass_id,
            "role": self.role,
            "state": self.state,
            "claimed_by": self.claimed_by,
            "model": self.model,
            "outcome": self.outcome,
            "notes": self.notes,
            "reflection": self.reflection,
            "watched_step": self.watched_step,
            "park": self.park.as_dict(),
            "deps": self.deps,
            "blocked_by": self.blocked_by,
            "created_at": self.created_at,
            "fired_at": self.fired_at,
            "closed_at": self.closed_at,
            "active_seconds": self.active_seconds,
            "usage_input_tokens": self.usage_input_tokens,
            "usage_output_tokens": self.usage_output_tokens,
            "usage_cache_read_tokens": self.usage_cache_read_tokens,
            "usage_cache_creation_tokens": self.usage_cache_creation_tokens,
            "usage_cost_usd": self.usage_cost_usd.to_usd(),
            "usage_cost_basis": self.usage_cost_basis,
            "usage_thinking_tokens": self.usage_thinking_tokens,
            "turn_count": self.turn_count,
        }
