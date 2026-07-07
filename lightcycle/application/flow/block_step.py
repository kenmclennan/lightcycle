from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BlockInput:
    step: str
    needs: str
    branch: Optional[str] = None
    pr: Optional[str] = None
    reason: Optional[str] = None
    tried: Optional[str] = None


class BlockStepUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: BlockInput) -> None:
        resume = {}
        for k, v in (
            ("branch", input.branch),
            ("pr", input.pr),
            ("reason", input.reason),
            ("tried", input.tried),
            ("needs", input.needs),
        ):
            if v:
                resume[k] = v
        self._store.update_metadata(input.step, resume)
        self._store.route_to_human(input.step, "BLOCKED: %s" % input.needs)
