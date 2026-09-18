from dataclasses import dataclass

from lightcycle.application.goals._common import require_text


@dataclass(frozen=True)
class CreateGoalInput:
    title: str
    outcome: str = ""
    scope: str = ""


class CreateGoalUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, inp):
        title = require_text(inp.title, "title")
        return self._store.create_goal(title, inp.outcome or "", inp.scope or "")
