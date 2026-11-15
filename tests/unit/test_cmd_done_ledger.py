import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from lightcycle import cli
from lightcycle.application.errors import UseCaseError
from lightcycle.commands import flow as flow_cmds
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step
from lightcycle.application.work.gate_hold import GateHold
from lightcycle.domain.work import State
from tests.unit.test_cmd_close import _Container
from tests.unit.test_feedback_routed_close import flow_service, outcome_notes, world


def _call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = fn(list(args)) or 0
    return rc, out.getvalue(), err.getvalue()


class _ClockedContainer(_Container):
    clock = staticmethod(lambda: 1600.0)
    github = None


class TestCmdDoneAdvancesTheLedger(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_ClockedContainer(self.store))
        self.addCleanup(cli.set_container, None)

    def test_a_refused_step_close_does_not_advance_the_ledger(self):
        step = create_owned_step(self.store, "build: x", stage="build", role="agent")
        with mock.patch.object(
            flow_cmds, "RecordMergedGateRunUseCase"
        ), mock.patch.object(
            flow_cmds, "CompleteStepUseCase"
        ) as complete, mock.patch.object(
            flow_cmds, "AdvanceFeedbackLedgerUseCase"
        ) as ledger:
            complete.return_value.execute.side_effect = UseCaseError("refused")
            rc, out, err = _call(cli.cmd_done, step, "done")
        self.assertEqual(rc, 1)
        ledger.assert_not_called()

    def test_an_item_close_does_not_call_the_use_case(self):
        item = self.store.create_item("an item", "a description")
        with mock.patch.object(flow_cmds, "AdvanceFeedbackLedgerUseCase") as ledger:
            rc, out, err = _call(cli.cmd_done, item, "done", "--disposition", "completed")
        self.assertEqual(rc, 0, err)
        ledger.assert_not_called()

    def test_a_successful_step_close_advances_the_ledger_once(self):
        step = create_owned_step(self.store, "build: x", stage="build", role="agent")
        with mock.patch.object(
            flow_cmds, "RecordMergedGateRunUseCase"
        ), mock.patch.object(
            flow_cmds, "CompleteStepUseCase"
        ) as complete, mock.patch.object(
            flow_cmds, "AdvanceFeedbackLedgerUseCase"
        ) as ledger:
            complete.return_value.execute.return_value = mock.Mock(
                next_step=None, teardown_refusal=None)
            rc, out, err = _call(cli.cmd_done, step, "done")
        self.assertEqual(rc, 0, err)
        ledger.return_value.execute.assert_called_once_with(step)


class TestCmdDonePassesMergedPrsToComplete(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_ClockedContainer(self.store))
        self.addCleanup(cli.set_container, None)

    def test_the_pass_end_merged_prs_reach_the_complete_input(self):
        step = create_owned_step(self.store, "build: x", stage="build", role="agent")
        with mock.patch.object(
            flow_cmds, "RecordMergedGateRunUseCase"
        ) as gate, mock.patch.object(
            flow_cmds, "CompleteStepUseCase"
        ) as complete, mock.patch.object(
            flow_cmds, "AdvanceFeedbackLedgerUseCase"
        ):
            gate.return_value.merged_prs_at_pass_end.return_value = frozenset({"https://x/pull/1"})
            complete.return_value.execute.return_value = mock.Mock(
                next_step=None, teardown_refusal=None)
            rc, out, err = _call(cli.cmd_done, step, "done")
        self.assertEqual(rc, 0, err)
        sent = complete.return_value.execute.call_args[0][0]
        self.assertEqual(sent.merged_prs, frozenset({"https://x/pull/1"}))


class _SpawnlessConfig:
    def max_title_length(self):
        return 200

    def spawn_id(self):
        return None


class TestCmdDoneRoutedFeedbackClose(unittest.TestCase):
    def setUp(self):
        self.store, self.item, self.gate, self.fb = world()
        container = _ClockedContainer(self.store)
        container.config = _SpawnlessConfig()
        cli.set_container(container)
        self.addCleanup(cli.set_container, None)
        patch = mock.patch.object(
            flow_cmds, "_flow", return_value=flow_service(self.store))
        patch.start()
        self.addCleanup(patch.stop)

    def _assert_both_unchanged(self):
        self.assertEqual(self.store.get_node(self.fb).state, State.RUNNING)
        self.assertEqual(self.store.get_node(self.gate).state, State.WAITING)
        self.assertEqual(outcome_notes(self.store, self.fb), [])
        self.assertEqual(outcome_notes(self.store, self.gate), [])

    def test_a_routed_close_with_a_note_over_the_caps_leaves_both_steps_unchanged(self):
        self._assert_both_unchanged()

        rc, out, err = _call(cli.cmd_done, self.fb, "rework", "--note", " ".join(["word"] * 60))

        self.assertEqual(rc, 2)
        self._assert_both_unchanged()

    def test_a_routed_close_on_a_held_gate_is_refused_and_leaves_both_steps_unchanged(self):
        GateHold(self.store).place(self.gate, "held for a decision")
        self._assert_both_unchanged()

        rc, out, err = _call(cli.cmd_done, self.fb, "rework", "--note", "fix the thing")

        self.assertEqual(rc, 1)
        self.assertIn(self.gate, err)
        self._assert_both_unchanged()
