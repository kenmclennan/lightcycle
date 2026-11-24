import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from lightcycle.adapters import workers as wk
from lightcycle.adapters.workers import WorkersAdapter
from lightcycle.application.pool.tick import TickInput
from lightcycle.ports.store import StoreError
from tests.support.fake_store import FakeStore
from tests.support.tick_factory import make_tick
from tests.unit.test_pool import FakeConfig, FakeSpawner


class _Config(FakeConfig):
    def worker_history(self):
        return 100

    def shutdown_grace_seconds(self):
        return 0


class _RaisingStore(FakeStore):
    def ready_steps(self):
        raise StoreError("boom")


class _Counter:
    def __init__(self):
        self.calls = []
        self.real = wk.run_in_group

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        return self.real(*args, **kwargs)

    def count_for(self, pid):
        return sum(1 for a in self.calls if str(pid) in [str(x) for x in a[0]])


class TestTickLivenessMemo(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "logs"))
        self.adapter = WorkersAdapter(_Config(root=self.root))

    def _live(self):
        child = subprocess.Popen(["sleep", "30"])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        return child

    def _dead_pid(self):
        child = subprocess.Popen(["true"])
        child.wait()
        return child.pid

    def test_tick_makes_at_most_one_ps_per_live_worker(self):
        live = self._live()
        now = 1000.0
        entries = [
            {"spawnid": "d%d" % i, "pid": self._dead_pid(), "pid_started": "t",
             "role": "agent", "step": None, "started": now - 9999}
            for i in range(20)
        ]
        entries.append({"spawnid": "live", "pid": live.pid, "pid_started": None,
                        "role": "agent", "step": None, "started": now - 1})
        wk.write_workers(self.root, entries)
        self.assertEqual(len(wk.workers_state(self.root)), 21)
        counter = _Counter()
        tick = make_tick(FakeStore(), self.adapter, FakeSpawner(), _Config(root=self.root))

        with mock.patch.object(wk, "run_in_group", counter):
            tick.execute(TickInput(now=now, since=None, drain=True))

        self.assertLessEqual(len(counter.calls), 1)
        self.assertEqual(counter.count_for(live.pid), 1)

    def test_memo_is_off_outside_a_tick(self):
        live = self._live()
        counter = _Counter()

        with mock.patch.object(wk, "run_in_group", counter):
            self.adapter.pid_alive(live.pid, None)
            self.adapter.pid_alive(live.pid, None)
            self.assertEqual(len(counter.calls), 2)
            self.adapter.begin_tick()
            self.adapter.pid_alive(live.pid, None)
            self.adapter.pid_alive(live.pid, None)
            self.assertEqual(len(counter.calls), 3)
            self.adapter.end_tick()
            self.adapter.pid_alive(live.pid, None)
            self.adapter.pid_alive(live.pid, None)

        self.assertEqual(len(counter.calls), 5)

    def test_kill_evicts_the_memo(self):
        child = subprocess.Popen(["sleep", "30"], start_new_session=True)
        self.addCleanup(child.kill)
        self.adapter.begin_tick()
        self.assertTrue(self.adapter.pid_alive(child.pid, None))

        self.adapter.kill(child.pid)
        child.wait()

        self.assertFalse(self.adapter.pid_alive(child.pid, None))

    def test_end_tick_runs_when_the_tick_raises(self):
        live = self._live()
        tick = make_tick(_RaisingStore(), self.adapter, FakeSpawner(), _Config(root=self.root))

        with self.assertRaises(StoreError):
            tick.execute(TickInput(now=1000.0, since=None, drain=False))

        counter = _Counter()
        with mock.patch.object(wk, "run_in_group", counter):
            self.adapter.pid_alive(live.pid, None)
            self.adapter.pid_alive(live.pid, None)
        self.assertEqual(len(counter.calls), 2)
