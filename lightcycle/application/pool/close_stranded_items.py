from dataclasses import dataclass, field
from typing import List, Tuple

from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.work.close_item import (
    CloseItemInput, CloseItemUseCase, TeardownRefused,
)
from lightcycle.domain.work import State

_RECOVERY_REASON = "auto-closed: all children done"


@dataclass(frozen=True)
class CloseStrandedItemsResponse:
    closed: List[str] = field(default_factory=list)
    refused: List[Tuple[str, str]] = field(default_factory=list)


class CloseStrandedItemsUseCase:
    def __init__(self, store, worktrees):
        self._store = store
        self._worktrees = worktrees
        self._closer = CloseItemUseCase(store, worktrees)

    def _stranded_children(self, item):
        children = self._store.children(item.id)
        if not children or any(c.state != State.DONE for c in children):
            return None
        newest = max(c.closed_at or "" for c in children)
        for state, ts in self._store.history(item.id):
            if state == str(State.DONE) and ts >= newest:
                return None
        return children

    def _repark(self, children, findings):
        newest = max(children, key=lambda c: (c.closed_at or "", c.id))
        ParkStepUseCase(self._store).execute_once(
            ParkInput(
                step=newest.id,
                observation="item close refused: %s" % "; ".join(findings),
                decision=(
                    "commit, push or discard the work named, then run lc done %s %s again"
                    % (newest.id, newest.outcome)
                ),
            )
        )

    def execute(self) -> CloseStrandedItemsResponse:
        closed = []
        refused = []
        for item in self._store.all_items():
            children = self._stranded_children(item)
            if children is None:
                continue
            try:
                self._closer.execute(CloseItemInput(
                    item=item.id, reason=_RECOVERY_REASON, disposition="completed"))
            except TeardownRefused as e:
                self._repark(children, e.findings)
                refused.append((item.id, "; ".join(e.findings)))
                continue
            closed.append(item.id)
        return CloseStrandedItemsResponse(closed=closed, refused=refused)
