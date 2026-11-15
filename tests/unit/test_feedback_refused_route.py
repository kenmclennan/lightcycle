import unittest
from unittest import mock

from lightcycle import cli
from lightcycle.application.flow import ParkInput, ParkStepUseCase
from lightcycle.application.flow.refused_route import RefusedRoute
from lightcycle.application.work.gate_hold import GateHold
from lightcycle.commands import flow as flow_cmds
from lightcycle.domain.work import State
from tests.support.fake_store import FakeStore
from tests.unit.test_atomic_completion import StubWorktrees
from tests.unit.test_cmd_done_ledger import _call, _ClockedContainer
from tests.unit.test_feedback_routed_close import (
    GRAPH, flow_service, outcome_notes, steps_at, world,
)

OVER_CAP = " ".join(["word"] * 60)
OK_NOTE = "fix the thing"


class _Config:
    def max_title_length(self):
        return 200

    def spawn_id(self):
        return None


class _LosingGateStore(FakeStore):
    lose_for = None

    def complete_step_atomic(self, tid, outcome, expected_assignee, next_step_spec):
        if tid == self.lose_for:
            return False, None
        return super().complete_step_atomic(tid, outcome, expected_assignee, next_step_spec)


class _Base(unittest.TestCase):
    store_class = FakeStore
    graph = GRAPH

    def setUp(self):
        self.store, self.item, self.gate, self.fb = world(self.store_class())
        container = _ClockedContainer(self.store)
        container.config = _Config()
        cli.set_container(container)
        self.addCleanup(cli.set_container, None)
        flow = flow_service(self.store, self.graph)
        patches = [
            mock.patch.object(flow_cmds, "_flow", return_value=flow),
            mock.patch.object(flow_cmds, "_worktrees", return_value=StubWorktrees()),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.latch = RefusedRoute(self.store)

    def assert_both_unchanged(self):
        self.assertEqual(self.store.get_node(self.fb).state, State.RUNNING)
        self.assertEqual(self.store.get_node(self.gate).state, State.WAITING)
        self.assertEqual(outcome_notes(self.store, self.fb), [])
        self.assertEqual(outcome_notes(self.store, self.gate), [])
        self.assertEqual(steps_at(self.store, "rework-stage"), [])


class TestRefusedRouteLatch(_Base):
    def _refuse_over_cap(self):
        rc, _out, _err = _call(cli.cmd_done, self.fb, "rework", "--note", OVER_CAP)
        self.assertEqual(rc, 2)

    def test_refused_over_cap_rework_then_done_is_refused(self):
        self.assert_both_unchanged()
        self.assertIsNone(self.latch.outcome_of(self.fb))

        self._refuse_over_cap()

        self.assertEqual(self.latch.outcome_of(self.fb), "rework")
        rc, _out, err = _call(cli.cmd_done, self.fb, "done", "--note", OK_NOTE)
        self.assertEqual(rc, 1)
        self.assertIn("rework", err)
        self.assertIn("park", err)
        self.assert_both_unchanged()

    def test_valid_rework_after_a_refusal_succeeds_and_clears_the_record(self):
        self._refuse_over_cap()
        self.assertEqual(self.latch.outcome_of(self.fb), "rework")

        rc, _out, err = _call(cli.cmd_done, self.fb, "rework", "--note", OK_NOTE)

        self.assertEqual(rc, 0, err)
        gate = self.store.get_node(self.gate)
        self.assertEqual((gate.state, gate.outcome), (State.DONE, "changes"))
        own = self.store.get_node(self.fb)
        self.assertEqual((own.state, own.outcome), (State.DONE, "rework"))
        self.assertIsNone(self.latch.outcome_of(self.fb))

    def test_park_is_allowed_after_a_refusal(self):
        self._refuse_over_cap()

        ParkStepUseCase(self.store).execute(
            ParkInput(step=self.fb, observation="note too long", decision="human decides"))

        self.assertEqual(self.store.get_node(self.fb).state, State.WAITING)
        self.assertEqual(self.latch.outcome_of(self.fb), "rework")

    def test_a_held_gate_refusal_records_the_latch(self):
        GateHold(self.store).place(self.gate, "hold it")

        rc, _out, err = _call(cli.cmd_done, self.fb, "rework", "--note", OK_NOTE)

        self.assertEqual(rc, 1)
        self.assertIn("held", err)
        self.assertEqual(self.latch.outcome_of(self.fb), "rework")
        self.assert_both_unchanged()

    def test_record_is_ignored_once_the_gate_is_done(self):
        self._refuse_over_cap()
        self.store.complete_step_atomic(self.gate, "merged", None, None)

        rc, _out, err = _call(cli.cmd_done, self.fb, "done", "--note", OK_NOTE)

        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store.get_node(self.fb).state, State.DONE)


class TestUseCaseRefusalRecords(_Base):
    store_class = _LosingGateStore

    def test_a_use_case_refusal_records_the_latch(self):
        self.store.lose_for = self.gate

        rc, _out, err = _call(cli.cmd_done, self.fb, "rework", "--note", OK_NOTE)

        self.assertEqual(rc, 1)
        self.assertIn("nothing was stored", err)
        self.assertEqual(self.latch.outcome_of(self.fb), "rework")
        self.assert_both_unchanged()


class TestRefusalsWhoseRemedyIsDone(_Base):
    def test_closed_gate_refusal_does_not_record(self):
        self.store.complete_step_atomic(self.gate, "merged", None, None)

        rc, _out, _err = _call(cli.cmd_done, self.fb, "rework", "--note", OK_NOTE)

        self.assertEqual(rc, 1)
        self.assertIsNone(self.latch.outcome_of(self.fb))
        rc, _out, err = _call(cli.cmd_done, self.fb, "done", "--note", OK_NOTE)
        self.assertEqual(rc, 0, err)


class TestNoWatchedStep(unittest.TestCase):
    def test_no_watched_step_refusal_does_not_record(self):
        store, _item, gate, fb = world(watched=False)
        container = _ClockedContainer(store)
        container.config = _Config()
        cli.set_container(container)
        self.addCleanup(cli.set_container, None)
        with mock.patch.object(flow_cmds, "_flow", return_value=flow_service(store)), \
                mock.patch.object(flow_cmds, "_worktrees", return_value=StubWorktrees()):
            rc, _out, _err = _call(cli.cmd_done, fb, "rework", "--note", OK_NOTE)
            self.assertEqual(rc, 1)
            self.assertIsNone(RefusedRoute(store).outcome_of(fb))
            rc, _out, err = _call(cli.cmd_done, fb, "done", "--note", OK_NOTE)
        self.assertEqual(rc, 0, err)
        self.assertEqual(store.get_node(gate).state, State.WAITING)


class TestUndeclaredStageRecordsNothing(_Base):
    graph = GRAPH.replace("  pr_feedback_route  fb  rework  changes\n", "")

    def test_stage_without_a_declaration_records_nothing(self):
        rc, _out, _err = _call(cli.cmd_done, self.fb, "rework", "--note", OVER_CAP)

        self.assertEqual(rc, 2)
        self.assertIsNone(self.latch.outcome_of(self.fb))
        rc, _out, err = _call(cli.cmd_done, self.fb, "done", "--note", OK_NOTE)
        self.assertEqual(rc, 0, err)


if __name__ == "__main__":
    unittest.main()
