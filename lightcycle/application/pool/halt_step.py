from dataclasses import dataclass
from typing import Tuple

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.work.held_steps import HeldSteps
from lightcycle.domain.work import State


@dataclass(frozen=True)
class HaltInput:
    target: str
    note: str


@dataclass(frozen=True)
class HaltResponse:
    step: str
    spawnid: str
    pid: int
    findings: Tuple[str, ...]


class HaltStepUseCase:
    def __init__(self, store, workers, worktrees):
        self._store = store
        self._workers = workers
        self._worktrees = worktrees
        self._held = HeldSteps(store, workers)

    def _held_steps(self, target):
        kind = self._store.type_of(target)
        if kind is None:
            raise UseCaseError("unknown node '%s'" % target)
        node = self._store.get_node(target)
        if node.state == State.DONE:
            raise UseCaseError("%s is closed; there is nothing to halt" % target)
        if kind == "step":
            worker = self._held.holder(node)
            return [(node, worker)] if worker is not None else []
        if kind == "item":
            return self._held.of_item(target)
        raise UseCaseError("'%s' is not an item or a step (type=%s)" % (target, kind))

    def execute(self, input: HaltInput) -> HaltResponse:
        held = self._held_steps(input.target)
        if not held:
            raise UseCaseError(
                "no worker is running %s; use `lc set` or `lc dep` instead" % input.target
            )
        if len(held) > 1:
            raise UseCaseError(
                "%s has several steps a worker is running (%s); give one step id"
                % (input.target, ", ".join(step.id for step, _ in held))
            )
        step, worker = held[0]
        findings = self._worktrees.halt_findings(step.id)
        detail = [f if f.endswith(".") else f + "." for f in findings] or [
            "There is no worktree to report."
        ]
        observation = "halted by the driver: %s %s" % (input.note, " ".join(detail))
        decision = "resume with `lc set %s --state ready`, or close the item" % step.id
        ParkStepUseCase(self._store).execute(ParkInput(step.id, observation, decision))
        self._workers.kill(worker.pid)
        return HaltResponse(
            step=step.id, spawnid=worker.spawnid, pid=worker.pid, findings=tuple(findings)
        )
