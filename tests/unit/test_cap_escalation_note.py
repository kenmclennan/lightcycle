import unittest

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.domain.work import State
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_store import FakeStore


class _FlowAdapter:
    def __init__(self, flow, limits):
        self._flow = flow
        self._limits = limits

    def workflow_for(self, step):
        return "wf"

    def unpinned_workflow(self, node):
        return None

    def load_flow(self, name=None, project=None):
        return self._flow

    def flow_next(self, step, outcome, name=None, project=None):
        return self._flow.next(step, outcome)

    def outcomes_for(self, step, name=None, project=None):
        return sorted(self._flow.step_def(step).routes.keys())

    def meta_for_step(self, step, name=None, project=None):
        return {}

    def step_declared(self, stage, name=None, project=None):
        return self._flow.declared(stage)

    def escalated_transition(self, transition, outcome, history, name=None, project=None):
        return self._flow.escalated_transition(transition, outcome, history, self._limits.get)

    def phase_for(self, node):
        return self._flow.step_def(getattr(node, "stage", None)).phase

    def phase_for_stage(self, stage, name=None):
        return "code"

    def ends_pass(self, stage, outcome, name=None):
        return False


def _flow(hook, declaration):
    return flow_from_metas({
        "watcher": {
            "model": "sonnet",
            "step": "watch-ci",
            "routes": {"ci-failed": "write-code", "rejected": "write-code"},
            hook: declaration,
        },
        "coder": {"model": "sonnet", "step": "write-code", "routes": {"done": "watch-ci"}},
        "reviewer": {"step": "review-ci", "routes": {}},
    })


class TestCapEscalationNote(unittest.TestCase):
    def _drive(self, flow, outcome, prior, limits=None):
        store = FakeStore()
        item = store.create_item("capped feature", "a description")
        for _ in range(prior):
            old = store.create_step(stage="watch-ci", role="agent", item=item)
            store.complete_node(old, outcome)
        step = store.create_step(stage="watch-ci", role="agent", item=item)
        complete = CompleteStepUseCase(store, _FlowAdapter(flow, limits or {}))
        done = complete.execute(CompleteInput(step=step, outcome=outcome))
        return store, done

    def _open_review_ci(self, store):
        return next(
            t for t in store.all_nodes()
            if t.type == "step" and t.stage == "review-ci" and t.state != State.DONE
        )

    def test_review_rounds_cap_names_cap_count_stage_and_limit_on_the_opened_step(self):
        flow = _flow("on_review_rounds_cap", "rejected  review-ci")

        store, done = self._drive(flow, "rejected", prior=5, limits={"review-rounds-cap": 5})

        notes = store.get_node(done.next_step).notes
        self.assertEqual(self._open_review_ci(store).id, done.next_step)
        self.assertIn("review_rounds_cap reached: 6 review-rework rounds at watch-ci (cap 5)", notes)

    def test_ci_failed_cap_says_ci_failed_with_count_stage_and_limit(self):
        flow = _flow("on_ci_failed_cap", "ci-failed  3  review-ci")

        store, done = self._drive(flow, "ci-failed", prior=3)

        notes = store.get_node(done.next_step).notes
        self.assertIn("ci_failed_cap reached: CI failed 4 times at watch-ci (cap 3)", notes)

    def test_a_step_below_the_cap_opens_without_a_cap_note(self):
        flow = _flow("on_ci_failed_cap", "ci-failed  3  review-ci")

        store, done = self._drive(flow, "ci-failed", prior=1)

        self.assertNotIn("reached", store.get_node(done.next_step).notes or "")
