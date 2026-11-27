import os
import subprocess
import sys
import tempfile
import time
import unittest

from lightcycle.adapters import spawner, step_scratch
from lightcycle.adapters import workers as wk
from lightcycle.config import Config

SPAWNER = (
    "import os,subprocess,sys;"
    "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)'],"
    "start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=dict(os.environ,TMPDIR=sys.argv[1]));"
    "print(p.pid,flush=True)"
)
SLEEPER = "import time;time.sleep(300)"


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return True
    return bool(out.stdout.strip()) and not out.stdout.strip().startswith("Z")


def _wait_dead(pid, deadline=15.0):
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


def _kill(pid):
    try:
        os.kill(pid, 9)
    except OSError:
        pass


class TestStepScratchReap(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.root, True)
        self.addCleanup(__import__("shutil").rmtree, step_scratch.scratch_root(self.root), True)

    def _stand_in(self, spawnid):
        folder = step_scratch.create_scratch(self.root, spawnid)
        out = subprocess.run(
            [sys.executable, "-c", SPAWNER, folder], capture_output=True, text=True, timeout=30,
            start_new_session=True,
        )
        grandchild = int(out.stdout.strip())
        self.addCleanup(_kill, grandchild)
        wk.write_workers(self.root, [{"spawnid": spawnid, "pid": 2 ** 22 + 5, "pid_started": None}])
        return folder, grandchild

    def test_process_that_left_the_group_is_killed_by_tmpdir_and_folder_removed(self):
        folder, grandchild = self._stand_in("aaaa0001")
        self.assertTrue(_alive(grandchild))
        self.assertTrue(os.path.isdir(folder))
        end = time.monotonic() + 30
        while os.path.exists(folder) and time.monotonic() < end:
            wk.prune_workers(self.root, 0, grace_seconds=0, alive=lambda p, s: False)
            time.sleep(0.2)
        self.assertTrue(_wait_dead(grandchild))
        self.assertFalse(os.path.exists(folder))

    def test_process_outside_the_step_is_left_alone(self):
        folder, grandchild = self._stand_in("aaaa0002")
        other = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, other, True)
        bystanders = [
            subprocess.Popen([sys.executable, "-c", SLEEPER], cwd=folder,
                             env=dict(os.environ, TMPDIR=other), start_new_session=True),
            subprocess.Popen([sys.executable, "-c", SLEEPER], cwd=folder, start_new_session=True),
            subprocess.Popen([sys.executable, "-c", SLEEPER],
                             env=dict(os.environ, TMPDIR=folder + "2"), start_new_session=True),
        ]
        for b in bystanders:
            self.addCleanup(b.wait)
            self.addCleanup(b.kill)
        end = time.monotonic() + 30
        while os.path.exists(folder) and time.monotonic() < end:
            wk.prune_workers(self.root, 0, grace_seconds=0, alive=lambda p, s: False)
            time.sleep(0.2)
        self.assertTrue(_wait_dead(grandchild))
        for b in bystanders:
            self.assertIsNone(b.poll())

    def test_real_spawn_then_exit_leaves_no_folder(self):
        config = Config(environ={"LC_HOME": self.root, "LC_MAX_AGENTS": "2",
                                 "LC_SPAWN_CMD": "touch $TMPDIR/x; exit 0"})
        result = spawner.spawn_worker(config, "agent")
        self.assertIsNotNone(result)
        end = time.monotonic() + 30
        while wk.pid_alive(result["pid"]) and time.monotonic() < end:
            wk.reap_children()
            time.sleep(0.1)
        wk.reap_children()
        for _ in range(50):
            wk.prune_workers(self.root, 0, grace_seconds=0)
            if not os.listdir(step_scratch.scratch_root(self.root)):
                break
            time.sleep(0.2)
        self.assertEqual(os.listdir(step_scratch.scratch_root(self.root)), [])


if __name__ == "__main__":
    unittest.main()
