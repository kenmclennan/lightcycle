from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.pr_lookups import _MIN_TIMESTAMP, flow_for, run_of, skip_unpinned
from lightcycle.domain.work import State, node_id_key, parse_timestamp
from lightcycle.ports.github import ReadFailure

CI_JUDGED_SHA = "ci-judged-sha"
PR_HEAD_SHA = "pr-head-sha"


@dataclass(frozen=True)
class DetectHeadMovedResponse:
    head_moved: List[str] = field(default_factory=list)


class DetectHeadMovedUseCase:
    def __init__(self, store, flow_service, complete):
        self._store = store
        self._flow_service = flow_service
        self._complete = complete

    def _artifact(self, step_id, atype):
        found = None
        for artifact in self._store.item_artifacts(step_id):
            if artifact.type == atype:
                found = artifact.value
        return found

    def _is_ci_stage(self, flow, node):
        sd = flow.step_def(node.stage)
        return sd.ci_success is not None or sd.ci_failure is not None

    def _judged_sha(self, step, flow):
        phase = flow.step_def(step.stage).phase
        latest = None
        latest_key = None
        for child in self._store.children(step.item):
            if child.type != "step" or child.state != State.DONE:
                continue
            if flow.step_def(child.stage).phase != phase or not self._is_ci_stage(flow, child):
                continue
            key = (parse_timestamp(child.created_at) or _MIN_TIMESTAMP, node_id_key(child.id))
            if latest_key is None or key > latest_key:
                latest, latest_key = child, key
        if latest is None:
            return None
        return self._artifact(latest.id, CI_JUDGED_SHA)

    def _feedback_in_flight(self, step):
        return any(
            node.type == "step" and node.state != State.DONE and node.watched_step == step.id
            for node in self._store.children(step.item)
        )

    def execute(self, reads) -> DetectHeadMovedResponse:
        if self._complete is None:
            return DetectHeadMovedResponse()
        head_moved = []
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE or not step.item:
                continue
            if skip_unpinned(self._store, self._flow_service, step):
                continue
            flow = flow_for(self._flow_service, step)
            sd = flow.step_def(step.stage)
            if sd.pr_merge is None or sd.pr_head_moved is None:
                continue
            run = run_of(self._store, self._flow_service, step)
            pr = run.pr if run else None
            if pr is None:
                continue
            sync = reads.read(pr)
            if isinstance(sync, ReadFailure) or not sync.head_sha:
                continue
            if self._feedback_in_flight(step):
                continue
            recorded = self._artifact(step.id, PR_HEAD_SHA)
            if recorded is None:
                recorded = self._judged_sha(step, flow)
                if recorded is None:
                    self._store.add_artifact(step.id, PR_HEAD_SHA, sync.head_sha, internal=True)
                    continue
                self._store.add_artifact(step.id, PR_HEAD_SHA, recorded, internal=True)
            if recorded != sync.head_sha:
                self._complete.execute(CompleteInput(step=step.id, outcome=sd.pr_head_moved))
                head_moved.append(step.item)
        return DetectHeadMovedResponse(head_moved=head_moved)
