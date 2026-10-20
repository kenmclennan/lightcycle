from dataclasses import dataclass, field
import time
from typing import List

from lightcycle.application.pool.check_content_pin import CheckContentPinUseCase
from lightcycle.application.pool.dispatch_pr_feedback import DispatchPrFeedbackUseCase
from lightcycle.application.pool.detect_head_moved import DetectHeadMovedUseCase
from lightcycle.application.pool.update_behind_prs import UpdateBehindPrsUseCase
from lightcycle.application.pool.pr_sync_reads import PrSyncReads
from lightcycle.application.pool.resolve_ci import ResolveCiUseCase
from lightcycle.application.pool.resolve_merged_prs import ResolveMergedPrsUseCase


@dataclass(frozen=True)
class MonitorPrsResponse:
    merged: List[str]
    abandoned: List[str] = field(default_factory=list)
    reworked: List[str] = field(default_factory=list)
    conflicted: List[str] = field(default_factory=list)
    ci_resolved: List[str] = field(default_factory=list)
    head_moved: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    update_failed: List[str] = field(default_factory=list)


class MonitorPrsUseCase:
    def __init__(
        self, store, github, worktrees, flow_service, complete=None, *,
        trusted_authors, held_shortcode,
    ):
        check_content_pin = CheckContentPinUseCase(
            store, github, flow_service, trusted_authors=trusted_authors
        )
        self._resolve = ResolveMergedPrsUseCase(
            store, github, worktrees, flow_service, complete, check_content_pin
        )
        self._github = github
        self._dispatch = DispatchPrFeedbackUseCase(
            store, github, flow_service, complete,
            trusted_authors=trusted_authors, held_shortcode=held_shortcode,
        )
        self._detect_head_moved = DetectHeadMovedUseCase(store, flow_service, complete)
        self._update_behind = UpdateBehindPrsUseCase(store, github, flow_service, time.monotonic)
        self._resolve_ci = ResolveCiUseCase(store, github, flow_service, complete)

    def execute(self) -> MonitorPrsResponse:
        resolved = self._resolve.execute()
        reads = PrSyncReads(self._github)
        dispatched = self._dispatch.execute(reads)
        moved = self._detect_head_moved.execute(reads)
        behind = self._update_behind.execute(reads)
        ci = self._resolve_ci.execute()
        return MonitorPrsResponse(
            merged=resolved.merged, abandoned=resolved.abandoned,
            reworked=dispatched.reworked, conflicted=dispatched.conflicted,
            ci_resolved=ci.ci_resolved, head_moved=moved.head_moved, updated=behind.updated,
            update_failed=behind.update_failed,
        )
