from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.goals._common import require_goal, require_text
from lightcycle.domain.goals import GOAL_STATUSES


@dataclass(frozen=True)
class EditGoalInput:
    id: str
    title: Optional[str] = None
    outcome: Optional[str] = None
    scope: Optional[str] = None
    status: Optional[str] = None


class EditGoalUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, inp):
        require_goal(self._store, inp.id)
        if all(v is None for v in (inp.title, inp.outcome, inp.scope, inp.status)):
            raise UseCaseError("nothing to set: pass --title, --outcome, --scope or --status")
        title = None if inp.title is None else require_text(inp.title, "title")
        if inp.status is not None and inp.status not in GOAL_STATUSES:
            raise UseCaseError(
                "invalid status %r: expected one of %s"
                % (inp.status, ", ".join(GOAL_STATUSES))
            )
        self._store.update_goal(
            inp.id, title=title, outcome=inp.outcome, scope=inp.scope, status=inp.status
        )
