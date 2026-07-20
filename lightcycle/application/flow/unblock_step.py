from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError


@dataclass(frozen=True)
class UnblockInput:
    step: str


@dataclass(frozen=True)
class UnblockResponse:
    role: str


class UnblockStepUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: UnblockInput) -> UnblockResponse:
        t = self._store.get_node(input.step)
        role = self._flow.flow_for(t).owner_of(t.step)
        if not role or role == "human":
            raise UseCaseError(
                "nothing to unblock: step '%s' has no agent owner" % (t.step or "(none)")
            )
        self._store.update_metadata(
            input.step,
            {"theme": t.theme, "since": t.since, "fired_at": t.fired_at, "needs": None},
        )
        kept = [l for l in (t.notes or "").splitlines() if not l.startswith("BLOCKED:")]
        self._store.set_notes(input.step, "\n".join(kept))
        self._store.reassign(input.step, role)
        return UnblockResponse(role=role)
