from dataclasses import dataclass
from typing import Optional

from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase


@dataclass(frozen=True)
class BlockInput:
    step: str
    needs: str
    reason: str
    branch: Optional[str] = None
    pr: Optional[str] = None
    tried: Optional[str] = None


class BlockStepUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: BlockInput) -> None:
        ParkStepUseCase(self._store).execute(ParkInput(
            step=input.step, observation=input.reason, decision=input.needs,
            branch=input.branch, pr=input.pr, tried=input.tried,
        ))
