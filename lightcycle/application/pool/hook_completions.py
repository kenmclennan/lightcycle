import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from lightcycle.domain.work import parse_timestamp


@dataclass(frozen=True)
class HookCompletionsResponse:
    completed: List[Tuple[str, str, str]] = field(default_factory=list)


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat()


class HookCompletionsUseCase:

    def __init__(self, store, flow_service):
        self._store = store
        self._flow_service = flow_service

    def execute(self, since: Optional[float]) -> HookCompletionsResponse:
        since_iso = _iso(since) if since is not None else None
        since_date = since_iso[:10] if since_iso else ""
        completed = []
        for node in self._store.nodes_closed_since(since_date):
            if not node.closed_at:
                continue
            if since_iso is not None and parse_timestamp(node.closed_at) <= parse_timestamp(since_iso):
                continue
            if node.stage in self._flow_service.flow_for(node).hook_steps():
                completed.append((node.stage, node.id, node.notes or node.outcome or ""))
        return HookCompletionsResponse(completed=completed)
