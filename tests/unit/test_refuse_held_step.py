import unittest
from unittest import mock

from lightcycle import cli
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.commands import flow as flow_cmds
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.null_collaborators import NoFlow
from tests.unit.test_atomic_completion import StubWorktrees, _complete
from tests.unit.test_halt_step import _Cfg, _Container, _held_item, call


class _Base(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.workers = FakeWorkers(alive_pids={101})
        cli.set_container(_Container(self.store, self.workers))
        patcher = mock.patch.object(
            flow_cmds, "_worktrees",
            lambda: WorktreeService(self.store, FakeGit(), FakeFs(), _Cfg(), NoFlow()),
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class TestHeldStepRefusesClose(_Base):
    def assert_refused(self, rc, err, item, step):
        self.assertEqual(rc, 1)
        self.assertIn("lc halt %s" % item, err)
        self.assertNotEqual(self.store.get_node(item).state, "done")
        self.assertEqual(self.store.get_node(step).state, "running")
        self.assertEqual(self.store.artifacts_of_type("teardown-refused"), [])

    def test_close_refuses_naming_halt(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers, with_run=False)
        rc, out, err = call(cli.cmd_close, item, "--disposition", "abandoned")
        self.assert_refused(rc, err, item, step)

    def test_done_on_an_item_refuses_naming_halt(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers, with_run=False)
        rc, out, err = call(cli.cmd_done, item, "done", "--disposition", "completed")
        self.assert_refused(rc, err, item, step)

    def test_close_proceeds_when_no_worker_is_alive(self):
        item, step = _held_item(self.store, "sp1", 999, self.workers, with_run=False)
        rc, out, err = call(cli.cmd_close, item)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store.get_node(item).state, "done")


class TestCascadeFromTheWorkersOwnFinalStepIsUnguarded(unittest.TestCase):
    def test_closing_the_item_from_the_held_final_step_still_succeeds(self):
        store = FakeStore()
        workers = FakeWorkers(alive_pids={101})
        item, step = _held_item(store, "sp1", 101, workers, with_run=False, stage="finalise")

        _complete(store, StubWorktrees(), step)

        self.assertEqual(store.get_node(item).state, "done")


if __name__ == "__main__":
    unittest.main()
