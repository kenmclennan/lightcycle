import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

from lightcycle import cli
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.unblock_step import UnblockStepUseCase
from lightcycle.application.pool.halt_step import HaltInput, HaltStepUseCase
from lightcycle.ports.workers import RegistryUnreadable
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers

REPO = "/elsewhere/app"
BRANCH = "feat/app-x"


class _Cfg:
    def worktree_retries(self):
        return 0

    def worktree_retry_sleep(self):
        return 0

    def branch_prefix(self):
        return "feat"

    def projects_root(self):
        return "/projects"

    def engine_root(self):
        return "lightcycle"

    def max_title_length(self):
        return 200


class _Unreadable(FakeWorkers):
    def workers_state(self):
        raise RegistryUnreadable("registry is corrupt")


def _held_item(store, spawnid, pid, workers, title="story", with_run=True, stage="write-code"):
    item = store.create_item(title, "a description")
    store.add_artifact(item, "repo", REPO)
    if with_run:
        rid = store.open_run(item, store.open_pass(item), None)
        store.set_branch(rid, BRANCH)
    step = store.create_step(stage=stage, role="agent", item=item)
    store.claim_ready("agent", spawnid, item=item)
    workers.seed(workers._workers + [{"spawnid": spawnid, "pid": pid, "step": step, "role": "agent"}])
    return item, step


class _World(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.workers = FakeWorkers(alive_pids={101, 202})

    def halt(self, target, note="stop now"):
        return HaltStepUseCase(self.store, self.workers).execute(
            HaltInput(target=target, note=note)
        )


class TestHaltParksAndKills(_World):
    def test_item_given_parks_the_step_and_kills_only_that_worker(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers)

        resp = self.halt(item, "design caused a machine failure")

        node = self.store.get_node(step)
        self.assertEqual(node.state, "waiting")
        self.assertEqual(node.role, "human")
        self.assertIsNone(node.claimed_by)
        self.assertEqual(self.workers.killed, [101])
        self.assertEqual((resp.step, resp.spawnid, resp.pid), (step, "sp1", 101))
        reason = node.park.reason
        self.assertIn("halted by the driver: design caused a machine failure", reason)
        self.assertEqual(self.store.artifacts_of_type("teardown-refused"), [])

    def test_step_given_instead_of_item_gives_the_same_result(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers)

        self.halt(step)

        self.assertEqual(self.store.get_node(step).state, "waiting")
        self.assertEqual(self.workers.killed, [101])

    def test_a_worker_on_another_items_step_is_not_signalled(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers)
        other, other_step = _held_item(self.store, "sp2", 202, self.workers, title="other")

        self.halt(item)

        self.assertEqual(self.workers.killed, [101])
        self.assertEqual(self.store.get_node(other_step).state, "running")

    def test_halted_step_is_not_claimable_until_set_ready(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers)

        self.halt(step)

        self.assertIsNone(self.store.claim_ready("agent", "sp9"))

    def test_item_with_several_steps_halts_only_the_held_one(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers)
        later = self.store.create_step(stage="review", role="agent", item=item)

        resp = self.halt(item)

        self.assertEqual(resp.step, step)
        self.assertEqual(self.store.get_node(later).state, "queued")

class TestHaltRefusals(_World):
    def assert_refused(self, target, fragment=None, workers=None):
        before = [(n, self.store.get_node(n).state) for n in self._ids()]
        uc = HaltStepUseCase(self.store, workers or self.workers)
        with self.assertRaises(UseCaseError) as ctx:
            uc.execute(HaltInput(target=target, note="x"))
        if fragment:
            self.assertIn(fragment, str(ctx.exception))
        self.assertEqual(before, [(n, self.store.get_node(n).state) for n in self._ids()])
        self.assertEqual((workers or self.workers).killed, [])

    def _ids(self):
        return [r for r in self.store._records]

    def test_step_not_running(self):
        item = self.store.create_item("story", "d")
        step = self.store.create_step(stage="write-code", role="agent", item=item)
        self.workers.seed([{"spawnid": "sp1", "pid": 101, "step": step}])
        self.assert_refused(step, "lc set")

    def test_running_step_whose_worker_is_dead(self):
        item, step = _held_item(self.store, "sp1", 999, self.workers)
        self.assert_refused(item, "lc dep")

    def test_running_step_claimed_by_a_bare_role_with_no_registry_row(self):
        item = self.store.create_item("story", "d")
        step = self.store.create_step(stage="write-code", role="agent", item=item)
        self.store.claim_ready("agent")
        self.assert_refused(step, "no worker is running")

    def test_stale_row_with_a_different_spawnid_is_not_the_holder(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers)
        self.workers.seed([{"spawnid": "old", "pid": 202, "step": step}])
        self.assert_refused(step, "no worker is running")

    def test_unknown_id(self):
        self.assert_refused("NOPE-1", "unknown node")

    def test_closed_node(self):
        item = self.store.create_item("story", "d")
        self.store.update_state(item, "done")
        self.assert_refused(item, "closed")

    def test_unreadable_registry(self):
        workers = _Unreadable(alive_pids={101})
        item, step = _held_item(self.store, "sp1", 101, FakeWorkers(alive_pids={101}))
        self.assert_refused(item, "could not tell", workers=workers)

    def test_item_with_two_held_steps(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers)
        second = self.store.create_step(stage="review", role="agent", item=item)
        self.store.claim_ready("agent", "sp2", item=item)
        self.workers.seed(self.workers._workers + [{"spawnid": "sp2", "pid": 202, "step": second}])
        self.assert_refused(item, "give one step id")


class _Spin:
    def update(self, fn):
        pass


class _OwnerFlow:
    def flow_for(self, node):
        return SimpleNamespace(step_def=lambda stage: SimpleNamespace(owner="agent"))


class _Container:
    def __init__(self, store, workers):
        self.store = store
        self.workers = workers
        self.unblock_step_use_case = lambda: UnblockStepUseCase(
            store, _OwnerFlow(), spin_port=_Spin())
        self.config = _Cfg()
        self.git = None
        self.fs = None
        self.workflow_source = None
        self.workflow_bundle = None
        self.scaffold = None


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class TestCmdHalt(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.workers = FakeWorkers(alive_pids={101})
        cli.set_container(_Container(self.store, self.workers))

    def test_missing_note_exits_two_before_the_store_is_touched(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers, with_run=False)
        rc, out, err = call(cli.cmd_halt, item)
        self.assertEqual(rc, 2)
        self.assertEqual(self.workers.killed, [])
        self.assertEqual(self.store.get_node(step).state, "running")

    def test_halts_and_prints_the_resume_command(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers, with_run=False)
        rc, out, err = call(cli.cmd_halt, item, "--note", "stop", "now")
        self.assertEqual(rc, 0, err)
        self.assertIn("lc set %s --state ready" % step, out)
        self.assertEqual(self.workers.killed, [101])

    def test_set_ready_makes_a_halted_step_claimable_again(self):
        item, step = _held_item(self.store, "sp1", 101, self.workers, with_run=False)
        call(cli.cmd_halt, step, "--note", "stop")
        self.assertIsNone(self.store.claim_ready("agent", "sp9"))

        rc, out, err = call(cli.cmd_set, step, "--state", "ready")

        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store.claim_ready("agent", "sp9").id, step)

    def test_unheld_step_exits_one(self):
        item = self.store.create_item("story", "d")
        step = self.store.create_step(stage="write-code", role="agent", item=item)
        rc, out, err = call(cli.cmd_halt, step, "--note", "x")
        self.assertEqual(rc, 1)
        self.assertIn("no worker is running", err)


if __name__ == "__main__":
    unittest.main()
