from dataclasses import dataclass

from lightcycle.application.goals._common import require_text


@dataclass(frozen=True)
class CreateGoalInput:
    title: str
    description: str = ""
    project: str = ""


class CreateGoalUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, inp):
        title = require_text(inp.title, "title")
        project = require_text(inp.project, "project")
        return self._store.create_goal(title, inp.description or "", project)
