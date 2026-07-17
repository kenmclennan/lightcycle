import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


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
        since_date = since_iso[:10] if since_iso else ""
        cache = {}
        completed = []
        for node in self._store.nodes_closed_since(since_date):
            if not node.closed_at:
                continue
            if since_iso is not None and node.closed_at <= since_iso:
                continue
            if node.step in self._hook_steps_for(node, cache):
                completed.append((node.step, node.id, node.notes or node.outcome or ""))
        return HookCompletionsResponse(completed=completed)

    def _hook_steps_for(self, node, cache):
        pin = self._flow_service.workflow_for(node)
        if pin not in cache:
            flow = self._flow_service.load_flow(pin)
            cache[pin] = {step for step, _role in flow.hook_steps()}
        return cache[pin]
