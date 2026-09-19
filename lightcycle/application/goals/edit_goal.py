from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.goals._common import require_goal, require_text
from lightcycle.domain.goals import GOAL_STATUSES


@dataclass(frozen=True)
class EditGoalInput:
    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    project: Optional[str] = None
    status: Optional[str] = None


class EditGoalUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, inp):
        require_goal(self._store, inp.id)
        if all(v is None for v in (inp.title, inp.description, inp.project, inp.status)):
            raise UseCaseError("nothing to set: pass --title, --description, --project or --status")
        title = None if inp.title is None else require_text(inp.title, "title")
        project = None if inp.project is None else require_text(inp.project, "project")
        if inp.status is not None and inp.status not in GOAL_STATUSES:
            raise UseCaseError(
                "invalid status %r: expected one of %s"
                % (inp.status, ", ".join(GOAL_STATUSES))
            )
        self._store.update_goal(
            inp.id,
            title=title,
            description=inp.description,
            project=project,
            status=inp.status,
        )
