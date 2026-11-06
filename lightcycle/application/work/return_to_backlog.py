from dataclasses import dataclass
from typing import Tuple

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.work import State


@dataclass(frozen=True)
class ReturnToBacklogInput:
    item: str


@dataclass(frozen=True)
class ReturnToBacklogResponse:
    removed: Tuple[str, ...]


class ReturnToBacklogUseCase:
    def __init__(self, store):
        self._store = store

    def _reasons(self, node, open_steps):
        if node.state == State.DONE:
            return ["item %s is closed; use lc reopen %s to bring it back" % (node.id, node.id)]
        reasons = [
            "step %s is held by a worker - wait for it, or park it" % s.id
            for s in open_steps
            if s.state == State.RUNNING
        ]
        for run in self._store.open_runs_of(node.id):
            held = [
                label for label, value in (("branch", run.branch), ("PR", run.pr)) if value
            ]
            if held:
                reasons.append(
                    "run %s has a %s (%s) - there is work in flight to deal with first; "
                    "use lc close %s if the item is being dropped"
                    % (run.id, " and ".join(held),
                       ", ".join(v for v in (run.branch, run.pr) if v), node.id)
                )
        return reasons

    def execute(self, input: ReturnToBacklogInput) -> ReturnToBacklogResponse:
        with self._store.transaction():
            try:
                node = self._store.get_node(input.item)
            except KeyError:
                raise UseCaseError("no such node: %s" % input.item)
            if node.type != "item":
                raise UseCaseError("'%s' is not an item (type=%s)" % (input.item, node.type))
            open_steps = [
                c for c in self._store.children(node.id)
                if c.type == "step" and c.state != State.DONE
            ]
            reasons = self._reasons(node, open_steps)
            if not reasons and not open_steps:
                reasons = ["item %s is already in the backlog" % node.id]
            if reasons:
                raise UseCaseError("\n".join("refusing to backlog %s: %s" % (node.id, r)
                                             for r in reasons))
            for step in open_steps:
                self._store.delete(step.id)
        return ReturnToBacklogResponse(removed=tuple(s.id for s in open_steps))
