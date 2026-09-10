import os
import subprocess
import tempfile
import time
import unittest

from lightcycle.adapters import workers as wk

LEADER = "import subprocess,time;subprocess.Popen(['sleep','300']);time.sleep(0.2)"


def _in_group(pgid):
    out = subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True, text=True)
    return out.stdout.split()


def _spawn_leader_with_child():
    leader = subprocess.Popen(["python3", "-c", LEADER], start_new_session=True)
    time.sleep(0.6)
    leader.wait()
    return leader.pid


class TestWorkerGroupReap(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "logs"), exist_ok=True)
        self.strays = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for pgid in self.strays:
            try:
                os.killpg(pgid, 15)
            except OSError:
                pass

    def _register(self, pid, started=None):
        wk.register_worker(self.root, {"spawnid": "sp-%s" % pid, "role": "agent",
                                       "pid": pid, "pid_started": started, "step": None})

    def test_prune_reaps_a_dead_workers_orphaned_child(self):
        pid = _spawn_leader_with_child()
        self.strays.append(pid)
        self.assertTrue(_in_group(pid), "probe did not leave an orphan; test is not exercising the bug")
        self._register(pid)

        wk.prune_workers(self.root, keep_dead=0)

        time.sleep(0.4)
        self.assertEqual(_in_group(pid), [], "orphaned child survived prune_workers")

    def test_a_live_pid_is_never_signalled(self):
        live = subprocess.Popen(["sleep", "300"], start_new_session=True)
        self.addCleanup(live.kill)
        self.assertFalse(wk.reap_worker_group(live.pid))
        time.sleep(0.3)
        self.assertIsNone(live.poll(), "reap killed a live process group")

    def test_a_recycled_pid_is_never_signalled(self):
        live = subprocess.Popen(["sleep", "300"], start_new_session=True)
        self.addCleanup(live.kill)
        self._register(live.pid, started="1")
        self.assertFalse(
            wk.worker_alive(live.pid, "1"),
            "fixture is wrong: a mismatched pid_started should read as not-this-worker",
        )

        wk.prune_workers(self.root, keep_dead=0)

        time.sleep(0.3)
        self.assertIsNone(live.poll(), "prune signalled a recycled pid's group")

    def test_reap_is_idempotent_and_quiet_on_an_empty_group(self):
        pid = _spawn_leader_with_child()
        self.strays.append(pid)
        self.assertTrue(wk.reap_worker_group(pid))
        time.sleep(0.4)
        self.assertFalse(wk.reap_worker_group(pid))
