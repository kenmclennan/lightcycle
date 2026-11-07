import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from lightcycle import cli
from lightcycle.application.errors import UseCaseError
from lightcycle.commands import flow as flow_cmds
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step
from tests.unit.test_cmd_close import _Container


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
