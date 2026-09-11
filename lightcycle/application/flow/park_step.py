from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.work.park import Park


@dataclass(frozen=True)
class ParkInput:
    step: str
    observation: str
    decision: str
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
        park = Park(reason=input.observation, needs=input.decision, tried=input.tried)
        with self._store.transaction():
            self._store.update_metadata(input.step, {k: v for k, v in park.as_dict().items() if v})
            self._store.note(input.step, park.as_blocked_note())
            self._store.reassign(input.step, "human")
