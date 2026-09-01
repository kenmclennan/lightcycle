from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError


@dataclass(frozen=True)
class ParkInput:
    step: str
    observation: str
    decision: str
    branch: Optional[str] = None
    pr: Optional[str] = None
    tried: Optional[str] = None


class ParkStepUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: ParkInput) -> None:
        if not (input.observation or "").strip():
            raise UseCaseError(
                "cannot park %s: an observation (what happened) is required" % input.step
            )
        if not (input.decision or "").strip():
            raise UseCaseError(
                "cannot park %s: a decision (what the human must judge) is required" % input.step
            )
        resume = {}
        for k, v in (
            ("branch", input.branch),
            ("pr", input.pr),
            ("tried", input.tried),
            ("reason", input.observation),
            ("needs", input.decision),
        ):
            if v:
                resume[k] = v
        self._store.update_metadata(input.step, resume)
        self._store.route_to_human(input.step, "BLOCKED: %s" % input.decision)
