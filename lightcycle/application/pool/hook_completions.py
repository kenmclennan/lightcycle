import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from lightcycle.domain.work.status import Status


@dataclass(frozen=True)
class HookCompletionsResponse:
    completed: List[Tuple[str, str, str]] = field(default_factory=list)


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).isoformat()


class HookCompletionsUseCase:

    def __init__(self, store, flow_service):
        self._store = store
        self._flow_service = flow_service

    def execute(self, since: Optional[float]) -> HookCompletionsResponse:
        since_iso = _iso(since) if since is not None else None
        flow = self._flow_service.load_flow()
        completed = []
        for step, _role in flow.hook_steps():
            for task in self._store.tasks_at_step(step):
                if task.status != Status.DONE or not task.closed_at:
                    continue
                if since_iso is not None and task.closed_at <= since_iso:
                    continue
                completed.append((step, task.id, task.notes or task.outcome or ""))
        return HookCompletionsResponse(completed=completed)
