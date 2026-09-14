from dataclasses import dataclass, field
from typing import List

from lightcycle.application.pool.check_content_pin import CheckContentPinUseCase
from lightcycle.application.pool.dispatch_pr_feedback import DispatchPrFeedbackUseCase
from lightcycle.application.pool.resolve_ci import ResolveCiUseCase
from lightcycle.application.pool.resolve_merged_prs import ResolveMergedPrsUseCase


@dataclass(frozen=True)
class MonitorPrsResponse:
    merged: List[str]
    abandoned: List[str] = field(default_factory=list)
    reworked: List[str] = field(default_factory=list)
    conflicted: List[str] = field(default_factory=list)
    ci_resolved: List[str] = field(default_factory=list)


class MonitorPrsUseCase:
    def __init__(
        self, store, github, worktrees, flow_service, complete=None, *,
        spin_port, git=None, config=None
    ):
        check_content_pin = CheckContentPinUseCase(store, github)
        self._resolve = ResolveMergedPrsUseCase(
            store, github, worktrees, flow_service, complete, check_content_pin
        )
        self._dispatch = DispatchPrFeedbackUseCase(store, github, flow_service, complete)
        self._resolve_ci = ResolveCiUseCase(store, github, git, worktrees, flow_service, complete)

    def execute(self) -> MonitorPrsResponse:
        resolved = self._resolve.execute()
        dispatched = self._dispatch.execute()
        ci = self._resolve_ci.execute()
        return MonitorPrsResponse(
            merged=resolved.merged, abandoned=resolved.abandoned,
            reworked=dispatched.reworked, conflicted=dispatched.conflicted,
            ci_resolved=ci.ci_resolved,
        )
