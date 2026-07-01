"""BlockTask: escalate a task to a human with resume-state."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BlockInput:
    task: str
    needs: str
    branch: Optional[str] = None
    pr: Optional[str] = None
    reason: Optional[str] = None
    tried: Optional[str] = None


class BlockTaskUseCase:

    def __init__(self, store):
        self._store = store

    def execute(self, input: BlockInput) -> None:
        resume = {}
        for k, v in (("branch", input.branch), ("pr", input.pr), ("reason", input.reason),
                     ("tried", input.tried), ("needs", input.needs)):
            if v:
                resume[k] = v
        self._store.update_metadata(input.task, resume)
        self._store.note(input.task, "BLOCKED: %s" % input.needs)
        role = self._store.get_task(input.task).role
        if role and role != "human":
            self._store.label_remove(input.task, "for:%s" % role)
        self._store.label_add(input.task, "for:human")
        self._store.update_status(input.task, "open")
        self._store.assign(input.task, "")
