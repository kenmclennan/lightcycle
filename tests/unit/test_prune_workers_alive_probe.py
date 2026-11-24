import os
import tempfile
import unittest

from lightcycle.adapters import workers as wk


def _entry(n):
    return {"spawnid": "s%d" % n, "pid": 1000 + n, "pid_started": "t"}


class TestPruneUsesInjectedProbe(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        os.makedirs(os.path.join(self.root, "logs"))

    def test_prune_uses_the_injected_probe(self):
        wk.write_workers(self.root, [_entry(i) for i in range(4)])
        asked = []

        def probe(pid, started):
            asked.append(pid)
            return pid == 1003

        dropped = wk.prune_workers(self.root, keep_dead=1, alive=probe)

        self.assertEqual(sorted(asked), [1000, 1001, 1002, 1003])
        self.assertEqual(dropped, 2)
        kept = [w["pid"] for w in wk.workers_state(self.root)]
        self.assertEqual(kept, [1002, 1003])

    def test_mixed_answers_drop_only_dead_beyond_keep_dead(self):
        wk.write_workers(self.root, [_entry(i) for i in range(5)])

        dropped = wk.prune_workers(
            self.root, keep_dead=0, alive=lambda pid, started: pid in (1001, 1004))

        self.assertEqual(dropped, 3)
        self.assertEqual([w["pid"] for w in wk.workers_state(self.root)], [1001, 1004])
