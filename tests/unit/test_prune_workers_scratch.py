import os
import signal
import tempfile
import unittest
from unittest import mock

from lightcycle.adapters import step_scratch
from lightcycle.adapters import workers as wk

GRACE = 10
DEAD_PID = 2 ** 22 + 11


class Rig:
    def __init__(self, test):
        self.root = tempfile.mkdtemp()
        test.addCleanup(__import__("shutil").rmtree, self.root, True)
        self.tagged = {}
        self.signals = []

    def folder(self, spawnid):
        return step_scratch.create_scratch(self.root, spawnid)

    def prune(self, now, alive=lambda pid, started: False, keep_dead=0):
        return wk.prune_workers(
            self.root, keep_dead, grace_seconds=GRACE, now=lambda: now, alive=alive,
            tagged=lambda paths: {p: list(self.tagged.get(p, [])) for p in paths},
            signaller=lambda pids, sig: self.signals.append((list(pids), sig)),
        )


def entry(spawnid, pid=DEAD_PID):
    return {"spawnid": spawnid, "pid": pid, "pid_started": None}


class TestPruneWorkersScratch(unittest.TestCase):
    def test_dead_worker_with_empty_group_and_no_tagged_pids_is_deleted_and_dropped(self):
        rig = Rig(self)
        folder = rig.folder("dead0001")
        wk.write_workers(rig.root, [entry("dead0001")])
        self.assertEqual(rig.prune(0), 1)
        self.assertFalse(os.path.exists(folder))
        self.assertEqual(wk.workers_state(rig.root), [])

    def test_tagged_process_gets_term_then_kill_after_grace_and_folder_survives_until_gone(self):
        rig = Rig(self)
        folder = rig.folder("dead0001")
        rig.tagged[folder] = [4242]
        wk.write_workers(rig.root, [entry("dead0001")])
        self.assertEqual(rig.prune(0), 0)
        self.assertEqual(rig.prune(GRACE - 1), 0)
        self.assertTrue(os.path.isdir(folder))
        self.assertEqual(wk.workers_state(rig.root)[0]["scratch_term_at"], 0)
        self.assertEqual(rig.signals, [([4242], signal.SIGTERM)])
        self.assertEqual(rig.prune(GRACE), 0)
        self.assertEqual(rig.signals[-1], ([4242], signal.SIGKILL))
        self.assertTrue(os.path.isdir(folder))
        rig.tagged.clear()
        self.assertEqual(rig.prune(GRACE + 1), 1)
        self.assertFalse(os.path.exists(folder))

    def test_live_worker_folder_is_never_touched(self):
        rig = Rig(self)
        folder = rig.folder("live0001")
        rig.tagged[folder] = [4242]
        wk.write_workers(rig.root, [entry("live0001", pid=os.getpid())])
        self.assertEqual(rig.prune(0, alive=lambda pid, started: True), 0)
        self.assertTrue(os.path.isdir(folder))
        self.assertEqual(rig.signals, [])

    def test_mixed_dead_entries(self):
        rig = Rig(self)
        clean = rig.folder("clean001")
        busy = rig.folder("busy0001")
        live = rig.folder("live0001")
        rig.tagged[busy] = [4242]
        live_pid = os.getpid()
        wk.write_workers(
            rig.root, [entry("clean001"), entry("busy0001"), entry("live0001", pid=live_pid)]
        )
        dropped = rig.prune(0, alive=lambda pid, started: pid == live_pid)
        self.assertEqual(dropped, 1)
        self.assertFalse(os.path.exists(clean))
        self.assertTrue(os.path.isdir(busy))
        self.assertTrue(os.path.isdir(live))
        self.assertEqual(
            sorted(w["spawnid"] for w in wk.workers_state(rig.root)), ["busy0001", "live0001"]
        )

    def test_stray_folder_age_guard(self):
        rig = Rig(self)
        folder = rig.folder("stray001")
        os.utime(folder, (1000, 1000))
        wk.write_workers(rig.root, [])
        rig.prune(1000 + step_scratch.UNREGISTERED_SCRATCH_MIN_AGE_SECONDS - 1)
        self.assertTrue(os.path.isdir(folder))
        rig.prune(1000 + step_scratch.UNREGISTERED_SCRATCH_MIN_AGE_SECONDS)
        self.assertFalse(os.path.exists(folder))

    def test_stray_folder_with_marker_follows_grace(self):
        rig = Rig(self)
        folder = rig.folder("stray001")
        rig.tagged[folder] = [4242]
        wk.write_workers(rig.root, [])
        step_scratch.write_marker(folder, 5000)
        rig.prune(5000 + GRACE)
        self.assertEqual(rig.signals, [([4242], signal.SIGKILL)])
        rig.tagged.clear()
        rig.prune(5000 + GRACE + 1)
        self.assertFalse(os.path.exists(folder))

    def test_unlink_failure_keeps_entry_for_retry(self):
        rig = Rig(self)
        folder = rig.folder("dead0001")
        wk.write_workers(rig.root, [entry("dead0001")])
        with mock.patch("lightcycle.adapters.workers.shutil.rmtree"):
            self.assertEqual(rig.prune(0), 0)
        self.assertEqual(len(wk.workers_state(rig.root)), 1)
        self.assertEqual(rig.prune(1), 1)
        self.assertFalse(os.path.exists(folder))

    def test_no_scan_when_no_folder_exists(self):
        rig = Rig(self)
        wk.write_workers(rig.root, [entry("dead0001")])
        scan = mock.Mock()
        wk.prune_workers(rig.root, 0, alive=lambda p, s: False, tagged=scan)
        scan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
