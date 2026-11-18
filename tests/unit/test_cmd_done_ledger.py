import json
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


_REPO = "/elsewhere/app"
_LAYERS = ("layer-1", "layer-2", "layer-3")


class TestCmdDoneOnAStackedItem(unittest.TestCase):
    def _world(self, states, stack_read_fails=False, seeded=None):
        from lightcycle.application.services.worktree import WorktreeService
        from lightcycle.domain.pool import stack_shape
        from tests.support.fake_git import FakeGit
        from tests.support.fake_github import FakeGitHub
        from tests.support.null_collaborators import NoFlow
        from tests.support.stacked import STACK_URL, build_stack
        from tests.unit.test_close_item_teardown_guard import _Cfg

        store = FakeStore()
        item = store.create_item("stacked", "a description")
        store.add_artifact(item, "repo", _REPO)
        rid = store.open_run(item, store.open_pass(item), None)
        store.set_branch(rid, "layer-3")
        store.set_stack(rid, STACK_URL)
        if seeded:
            store.set_stack_seen(rid, stack_shape.encode(seeded))
        layers = build_stack(3, states=states)
        github = FakeGitHub(stacks={STACK_URL: layers})
        if stack_read_fails:
            github._failing_calls = {"stack_view"}
        branches = {(_REPO, b) for b in _LAYERS}
        git = FakeGit(branches=branches, ref="origin/main", beyond={k: ["a1"] for k in branches})
        svc = WorktreeService(store, git, fs=None, config=_Cfg(), flow=NoFlow())

        class _Container(_ClockedContainer):
            pass

        container = _Container(store)
        container.github = github
        container.worker_log = mock.Mock()
        cli.set_container(container)
        self.addCleanup(cli.set_container, None)
        patcher = mock.patch.object(flow_cmds, "_worktrees", lambda: svc)
        patcher.start()
        self.addCleanup(patcher.stop)
        return store, item, git

    def test_done_merged_on_a_squash_merged_three_layer_stack_succeeds_with_branches_present(self):
        store, item, git = self._world({1: "merged", 2: "merged", 3: "merged"})

        rc, out, err = _call(cli.cmd_done, item, "merged", "--disposition", "completed")

        self.assertEqual(rc, 0, err)
        self.assertEqual(store.get_node(item).state, State.DONE)
        self.assertEqual([a for a in store.item_artifacts(item) if a.type == "teardown-refused"], [])
        deleted = sorted(c[2] for c in git.calls if c[0] == "delete_branch")
        self.assertEqual(deleted, sorted(_LAYERS))

    def test_done_merged_refuses_only_the_layer_recorded_open_when_the_stack_cannot_be_read(self):
        seeded = [
            {"number": 1, "state": "merged", "head_ref": "layer-1", "base": "main"},
            {"number": 2, "state": "open", "head_ref": "layer-2", "base": "layer-1"},
            {"number": 3, "state": "merged", "head_ref": "layer-3", "base": "layer-2"},
        ]
        store, item, git = self._world(
            {1: "merged", 2: "merged", 3: "merged"}, stack_read_fails=True, seeded=seeded)

        rc, out, err = _call(cli.cmd_done, item, "merged", "--disposition", "completed")

        self.assertEqual(rc, 1)
        self.assertIn("layer-2", err)
        self.assertNotIn("layer-1 ", err)
        self.assertNotIn("branch layer-3", err)
        self.assertNotEqual(store.get_node(item).state, State.DONE)


class TestCmdDoneRebaselinesOnReopen(unittest.TestCase):
    def test_done_on_a_stack_review_step_with_reopen_rebaselines_the_run(self):
        from tests.support.stacked import build_stack
        from tests.unit.test_detect_stack_shape import _Rig
        from tests.unit.test_rebaseline_stack_on_reopen import _FLOW, _review_step, _seen

        rig = _Rig(build_stack(3), flow=_FLOW)
        container = _ClockedContainer(rig.store)
        container.github = rig.github
        cli.set_container(container)
        self.addCleanup(cli.set_container, None)
        review = _review_step(rig)
        self.assertIsNone(_seen(rig))

        with mock.patch.object(flow_cmds, "_flow", return_value=rig.flow), mock.patch.object(
            flow_cmds, "RecordMergedGateRunUseCase"
        ), mock.patch.object(
            flow_cmds, "CompleteStepUseCase"
        ) as complete, mock.patch.object(
            flow_cmds, "AdvanceFeedbackLedgerUseCase"
        ):
            complete.return_value.execute.return_value = mock.Mock(
                next_step=None, teardown_refusal=None)
            rc, out, err = _call(cli.cmd_done, review, "reopen")

        self.assertEqual(rc, 0, err)
        self.assertEqual([e["number"] for e in json.loads(_seen(rig))], [1, 2, 3])
