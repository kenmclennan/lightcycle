from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class PurgeResponse:
    removed: List[str] = field(default_factory=list)


class PurgeWorkflowDataUseCase:
    def __init__(self, lifecycle):
        self._lifecycle = lifecycle

    def execute(self, origin, workflow=None) -> PurgeResponse:
        return PurgeResponse(removed=self._lifecycle.purge(origin, workflow))
