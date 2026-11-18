import re
from dataclasses import dataclass, field
from typing import List

from lightcycle.application.pool.pr_lookups import flow_for, run_of, skip_unpinned
from lightcycle.application.pool.stack_reads import read_stack
from lightcycle.domain.pool import stack_shape
from lightcycle.domain.work import State
from lightcycle.ports.github import ReadFailure

DRAFT_PREFIX = "draft-pr:"
DRAFT_TEXT = "is a draft, so GitHub will refuse to merge it"
_TRAILER = re.compile(r" \(x\d+, last [^)]*\)$")


@dataclass(frozen=True)
class NoteDraftPrsResponse:
    noted: List[str] = field(default_factory=list)


class NoteDraftPrsUseCase:
    def __init__(self, store, github, flow_service):
        self._store = store
        self._github = github
        self._flow_service = flow_service

    def _drafts(self, run, reads):
        if not run.stack:
            sync = reads.read(run.pr)
            if isinstance(sync, ReadFailure):
                return None
            return [run.pr] if sync.draft else []
        stack = read_stack(self._github, run.stack)
        if not stack.layers:
            return None
        total = len(stack.layers)
        drafts = []
        for position, layer in enumerate(stack.layers, start=1):
            if layer.state != "open":
                continue
            sync = reads.read(layer.url)
            if isinstance(sync, ReadFailure):
                return None
            if sync.draft:
                drafts.append(stack_shape.label(position, total, layer.url))
        return drafts

    def _record(self, step, drafts):
        if not drafts:
            if self._existing(step):
                self._store.clear_condition(step.id, DRAFT_PREFIX)
            return False
        line = "%s %s %s" % (DRAFT_PREFIX, "; ".join(drafts), DRAFT_TEXT)
        existing = self._existing(step)
        if any(_TRAILER.sub("", e) == line for e in existing):
            return False
        if existing:
            self._store.clear_condition(step.id, DRAFT_PREFIX)
        self._store.note_condition(step.id, line)
        return True

    def _existing(self, step):
        return [
            line for line in (self._store.get_node(step.id).notes or "").splitlines()
            if line.startswith(DRAFT_PREFIX)
        ]

    def execute(self, reads) -> NoteDraftPrsResponse:
        noted = []
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE or not step.item:
                continue
            if skip_unpinned(self._store, self._flow_service, step):
                continue
            flow = flow_for(self._flow_service, step)
            if "on_pr_merge" not in flow.step_def(step.stage).hooks:
                continue
            run = run_of(self._store, self._flow_service, step)
            if run is None or run.pr is None:
                continue
            drafts = self._drafts(run, reads)
            if drafts is None:
                continue
            if self._record(step, drafts):
                noted.append(step.item)
        return NoteDraftPrsResponse(noted=noted)
