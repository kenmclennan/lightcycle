import unittest
from signal import SIGCONT, SIGKILL, SIGTERM

from lightcycle.application.pool.reap_orphan_processes import (
    OrphanProcess, ReapOrphanProcessesUseCase,
)
from lightcycle.application.services.orphaned_worktrees import OrphanedWorktrees
from tests.support.fake_fs import FakeFs
from tests.support.fake_machine import FakeMachine
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers

GONE = "/repo/.worktrees/gone"
IDLE = "/repo/.worktrees/idle"


class _Worktrees:
    def __init__(self, paths=None):
        self._paths = paths or {}

    def worktree_path(self, node):
        return self._paths[node.item]


class _Config:
    def __init__(self, grace):
        self._grace = grace

    def shutdown_grace_seconds(self):
        return self._grace


class _Time:
    def __init__(self, step, machine=None):
        self.now = 0
        self.step = step
        self.machine = machine
        self.kill_seen_at = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        if seconds >= 1:
            return
        if self.machine is not None:
            self.kill_seen_at.append(
                (self.now, any(sig == SIGKILL for _pid, sig in self.machine.signalled)))
        self.now += self.step


def _rig(cwd_pids, alive, grace=10, step=1, workers=None, claimed=None, **machine_kwargs):
    store = FakeStore()
    store.add_project("acme", local_path="/repo")
    paths = {}
    if claimed:
        item = store.create_item("item", "a description")
        stepid = store.create_step(item=item, role="agent")
        store.update_state(stepid, "in_progress")
        paths[item] = claimed
    fs = FakeFs(dirs={"/repo/.worktrees": ["idle", "live"]})
    machine = FakeMachine(cwd_pids=cwd_pids, alive=alive, **machine_kwargs)
    timer = _Time(step, machine)
    orphans = OrphanedWorktrees(store, fs, machine, _Worktrees(paths), lambda s: None)
    use_case = ReapOrphanProcessesUseCase(
        orphans, workers or FakeWorkers(), machine, _Config(grace), timer.sleep, timer.clock)
    return use_case, machine, timer


class TestReapOrphanProcesses(unittest.TestCase):
    def test_term_then_kill_after_grace(self):
        use_case, machine, timer = _rig({GONE: [5]}, {5}, grace=10, step=5, stubborn={5})

        result = use_case.execute()

        self.assertEqual(machine.signalled[:2], [(5, SIGCONT), (5, SIGTERM)])
        self.assertIn((5, SIGKILL), machine.signalled)
        before = [seen for at, seen in timer.kill_seen_at if at < 10]
        self.assertTrue(before)
        self.assertFalse(any(before))
        self.assertEqual(result.ended, [OrphanProcess(5, GONE)])

    def test_pid_that_exits_on_term_gets_no_kill(self):
        use_case, machine, _timer = _rig({GONE: [5]}, {5})

        result = use_case.execute()

        self.assertEqual(machine.signalled, [(5, SIGCONT), (5, SIGTERM)])
        self.assertEqual(result.ended, [OrphanProcess(5, GONE)])

    def test_mixed_outcomes(self):
        use_case, _machine, _timer = _rig(
            {GONE: [5, 6, 7]}, {5, 6, 7}, stubborn={6, 7}, immortal={7})

        result = use_case.execute()

        self.assertEqual(result.ended, [OrphanProcess(5, GONE), OrphanProcess(6, GONE)])
        self.assertEqual(result.unended, [OrphanProcess(7, GONE)])

    def test_pid_that_left_the_worktree_before_kill_is_not_killed(self):
        use_case, machine, _timer = _rig(
            [{GONE: [5]}, {GONE: [5]}, {}], {5}, stubborn={5})

        result = use_case.execute()

        self.assertIn((5, SIGTERM), machine.signalled)
        self.assertNotIn((5, SIGKILL), machine.signalled)
        self.assertEqual(result.ended, [])
        self.assertEqual(result.unended, [])

    def test_nothing_outside_the_orphaned_worktree_is_signalled(self):
        use_case, machine, _timer = _rig(
            {GONE: [5], "/repo/.worktrees/live": [6], "/elsewhere": [7]},
            {5, 6, 7}, claimed="/repo/.worktrees/live")

        use_case.execute()

        self.assertEqual({pid for pid, _sig in machine.signalled}, {5})

    def test_live_registered_worker_pid_is_excluded(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "w1", "pid": 5, "step": "x", "log": "/l", "started": 0}],
            alive_pids={5})
        use_case, machine, _timer = _rig({GONE: [5, 6]}, {5, 6}, workers=workers)

        use_case.execute()

        self.assertEqual({pid for pid, _sig in machine.signalled}, {6})

    def test_empty_scan_sends_no_signal(self):
        use_case, machine, _timer = _rig({}, {5})

        result = use_case.execute()

        self.assertEqual(machine.signalled, [])
        self.assertEqual((result.ended, result.unended, result.left), ([], [], []))

    def test_process_in_existing_unclaimed_worktree_is_left_not_signalled(self):
        use_case, machine, _timer = _rig({GONE: [5], IDLE: [6]}, {5, 6})

        result = use_case.execute()

        self.assertTrue(machine.signalled)
        self.assertEqual({pid for pid, _sig in machine.signalled}, {5})
        self.assertEqual(result.left, [OrphanProcess(6, IDLE)])

    def test_zero_grace_kills_without_waiting(self):
        use_case, machine, timer = _rig({GONE: [5]}, {5}, grace=0, stubborn={5})

        result = use_case.execute()

        self.assertEqual(
            machine.signalled,
            [(5, SIGCONT), (5, SIGTERM), (5, SIGCONT), (5, SIGKILL)])
        self.assertEqual(result.ended, [OrphanProcess(5, GONE)])
        self.assertEqual(len(timer.kill_seen_at), 1)

    def test_pid_signal_pid_refused_is_in_neither_list(self):
        use_case, machine, _timer = _rig({GONE: [5]}, {5}, own_pids={5})

        result = use_case.execute()

        self.assertEqual(machine.signalled, [])
        self.assertEqual((result.ended, result.unended), ([], []))
