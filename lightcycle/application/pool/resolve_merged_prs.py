from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.pool.pr_lookups import (
    active_step_any,
    active_step_at,
    false_on_failure,
    flow_for,
    latest_step,
)
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.domain.runs import RunState


@dataclass(frozen=True)
class ResolveMergedPrsResponse:
    merged: List[str] = field(default_factory=list)
    abandoned: List[str] = field(default_factory=list)


class ResolveMergedPrsUseCase:
    def __init__(self, store, github, worktrees, flow_service, complete, check_content_pin):
        self._store = store
        self._github = github
        self._worktrees = worktrees
        self._flow_service = flow_service
        self._complete = complete
        self._check_content_pin = check_content_pin

    def _disposition_for_close(self, item, flow, outcome):
        disposition = flow.disposition_for(outcome)
        if disposition is not None:
            return disposition
        step = active_step_any(self._store, item.id) or latest_step(self._store, item.id)
        if step is not None:
            ParkStepUseCase(self._store).execute(
                ParkInput(
                    step=step.id,
                    observation=(
                        "PR resolved with outcome '%s', but the workflow does not declare "
                        "a disposition for it" % outcome
                    ),
                    decision=(
                        "declare 'disposition: %s completed' or 'disposition: %s aborted' "
                        "in the workflow bundle" % (outcome, outcome)
                    ),
                )
            )
        return None

    def _close_run(self, run, state):
        self._store.close_run(run.id, state)
        if self._worktrees is not None:
            self._worktrees.release_run(run)

    def execute(self) -> ResolveMergedPrsResponse:
        merged, abandoned = [], []
        close = CloseItemUseCase(self._store, self._worktrees)
        for item in self._store.all_nodes():
            if item.type != "item":
                continue
            if not any(r.pr for r in self._store.open_runs_of(item.id)):
                continue
            flow = flow_for(self._flow_service, item)
            resolved = False
            for stage in flow.merge_stages():
                sd = flow.step_def(stage)
                phase = sd.phase
                run = self._store.current_run(item.id, phase)
                pr_value = run.pr if run else None
                if pr_value is None:
                    continue
                self._check_content_pin.execute(item, pr_value, phase)
                merge_outcome = sd.pr_merge
                close_outcome = sd.pr_close
                if merge_outcome and false_on_failure(self._github.is_merged(pr_value)):
                    nxt = flow.next(stage, merge_outcome)
                    if nxt and nxt.to_step and not nxt.to_terminal:
                        step = active_step_at(self._store, item.id, stage)
                        if step is None:
                            continue
                        self._close_run(run, RunState.MERGED)
                        self._complete.execute(CompleteInput(step=step.id, outcome=merge_outcome))
                        merged.append(item.id)
                    else:
                        disposition = self._disposition_for_close(item, flow, merge_outcome)
                        if disposition is None:
                            continue
                        close.execute(
                            CloseItemInput(
                                item=item.id, reason=merge_outcome, disposition=disposition
                            )
                        )
                        resolved = True
                        merged.append(item.id)
                elif close_outcome and false_on_failure(self._github.is_closed_unmerged(pr_value)):
                    nxt = flow.next(stage, close_outcome)
                    if nxt and nxt.to_step and not nxt.to_terminal:
                        step = active_step_at(self._store, item.id, stage)
                        if step is None:
                            continue
                        self._close_run(run, RunState.ABANDONED)
                        self._complete.execute(CompleteInput(step=step.id, outcome=close_outcome))
                        abandoned.append(item.id)
                    else:
                        disposition = self._disposition_for_close(item, flow, close_outcome)
                        if disposition is None:
                            continue
                        close.execute(
                            CloseItemInput(
                                item=item.id, reason=close_outcome, disposition=disposition
                            )
                        )
                        resolved = True
                        abandoned.append(item.id)
                if resolved:
                    break
        return ResolveMergedPrsResponse(merged=merged, abandoned=abandoned)
