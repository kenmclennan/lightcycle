import os
from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.goals._common import require_text


@dataclass(frozen=True)
class CreateGoalInput:
    title: str
    description: Optional[str] = None
    project: str = ""


class CreateGoalUseCase:
    def __init__(self, store, fs, config):
        self._store = store
        self._fs = fs
        self._config = config

    def execute(self, inp):
        title = require_text(inp.title, "title")
        project = require_text(inp.project, "project")
        description = inp.description
        if description is None:
            description = self._template()
        return self._store.create_goal(title, description, project)

    def _template(self):
        path = os.path.join(self._config.prompts_root(), "templates", "goal.md")
        raw = self._fs.read_bytes(path)
        if raw is None:
            raise UseCaseError("goal template not found: %s" % path)
        return raw.decode("utf-8")
