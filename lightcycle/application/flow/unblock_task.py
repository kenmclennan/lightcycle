from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError


@dataclass(frozen=True)
class UnblockInput:
    task: str


@dataclass(frozen=True)
class UnblockResponse:
    role: str


class UnblockTaskUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: UnblockInput) -> UnblockResponse:
        t = self._store.get_task(input.task)
        role = self._flow.load_flow(
            self._flow.workflow_for(t), self._flow.project_for(t)
        ).owner_of(t.step)
        if not role or role == "human":
            raise UseCaseError(
                "nothing to unblock: step '%s' has no agent owner" % (t.step or "(none)")
            )
        self._store.update_metadata(
            input.task,
            {"epic": t.epic, "since": t.since, "fired_at": t.fired_at, "needs": None},
        )
        kept = [l for l in (t.notes or "").splitlines() if not l.startswith("BLOCKED:")]
        self._store.set_notes(input.task, "\n".join(kept))
        self._store.reassign(input.task, role)
        return UnblockResponse(role=role)
