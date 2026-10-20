import unittest

from lightcycle.application.work.step_detail import StepDetail
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.step_def import StepDef
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step

PR = "https://github.com/kenmclennan/lightcycle/pull/946"


class PhasedFlow:
    def __init__(self, phases, detail=None):
        self._flow = Flow({
            "write-code": StepDef(owner="agent", detail=detail),
            "open-spec": StepDef(owner="agent", detail=detail),
        })
        self._phases = phases

    def flow_for(self, node):
        return self._flow

    def phase_for(self, node):
        return self._phases.get(node.stage)


def keys_and_values(store, step, flow):
    entries, _ = StepDetail(store, flow).resolve(store.get_node(step), {}, [])
    return {e.key: e.value for e in entries}


class TestStepDetailPr(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.flow = PhasedFlow({"write-code": "code", "open-spec": "spec"})
        self.step = create_owned_step(self.store, "s", step="write-code", role="agent")
        self.item = self.store.get_node(self.step).item
        self.pid = self.store.open_pass(self.item)
        self.store.set_step_pass(self.step, self.pid)

    def test_a_later_step_of_the_phase_shows_the_pr_of_the_phase_run(self):
        self.store.set_pr(self.store.open_run(self.item, self.pid, "code"), PR)

        self.assertEqual(keys_and_values(self.store, self.step, self.flow)["pr"], PR)

    def test_a_pr_from_an_earlier_pass_run_of_the_phase_still_shows(self):
        self.store.set_pr(self.store.open_run(self.item, self.pid, "code"), PR)
        self.store.close_pass(self.pid)
        second = self.store.open_pass(self.item)
        self.store.set_step_pass(self.step, second)
        self.store.open_run(self.item, second, "code")

        self.assertEqual(keys_and_values(self.store, self.step, self.flow)["pr"], PR)

    def test_a_declared_detail_without_pr_gains_it_once_the_phase_has_one(self):
        flow = PhasedFlow({"write-code": "code"}, detail=("outcome",))
        self.store.set_pr(self.store.open_run(self.item, self.pid, "code"), PR)

        self.assertEqual(keys_and_values(self.store, self.step, flow)["pr"], PR)

    def test_a_step_of_a_phase_without_a_run_pr_does_not_show_one(self):
        self.store.set_pr(self.store.open_run(self.item, self.pid, "code"), PR)
        other = self.store.create_step(step="open-spec", role="agent", parent=self.item)
        self.store.set_step_pass(other, self.pid)

        self.assertNotIn("pr", keys_and_values(self.store, other, self.flow))
