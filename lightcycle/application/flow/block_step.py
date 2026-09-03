from dataclasses import dataclass
from typing import Optional

from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase


@dataclass(frozen=True)
class BlockInput:
    step: str
    needs: str
    reason: str
    tried: Optional[str] = None


class BlockStepUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: BlockInput) -> None:
        ParkStepUseCase(self._store).execute(ParkInput(
            step=input.step, observation=input.reason, decision=input.needs,
            tried=input.tried,
        ))
