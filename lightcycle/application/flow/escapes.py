import datetime

from lightcycle.domain.feedback import ReviewEscape
from lightcycle.domain.feedback.review_yield import (
    VIA_CHANGE_REQUEST,
    VIA_PR_COMMENT,
    authors_text,
    classify_source,
    latest_passing_verdict,
)
from lightcycle.domain.work import State


class EscapeRecorder:
    def __init__(self, store):
        self._store = store

    def record_change_request(self, flow, step, note):
        phase = flow.step_def(step.stage).phase
        run = self._store.current_run(step.item, phase)
        self._record(flow, step.id, step.item, run, VIA_CHANGE_REQUEST, note, (), frozenset())

    def record_pr_comment(self, flow, feedback_step_id, item, run, keys, authors, trusted):
        self._record(
            flow, feedback_step_id, item, run, VIA_PR_COMMENT, "\n".join(keys), authors, trusted)

    def _record(self, flow, trigger, item, run, via, note, authors, trusted):
        if run is None:
            return
        verdict = self._passing_verdict(flow, item, run)
        if verdict is None:
            return
        self._store.record_escape(ReviewEscape(
            trigger_step=trigger, item=item, run_id=run.id, verdict_step=verdict.id, via=via,
            at=datetime.datetime.now().astimezone().isoformat(), note=note or None,
            source=classify_source(authors, trusted), authors=authors_text(authors),
        ))

    def _passing_verdict(self, flow, item, run):
        passed = []
        for child in self._store.children(item):
            if getattr(child, "type", None) != "step" or child.state != State.DONE:
                continue
            if child.pass_id != run.pass_id:
                continue
            definition = flow.step_def(child.stage)
            if definition.review is None or definition.phase != run.phase:
                continue
            if child.outcome == definition.review:
                passed.append(child)
        return latest_passing_verdict(passed)
