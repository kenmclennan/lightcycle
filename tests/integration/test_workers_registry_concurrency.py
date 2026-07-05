import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from the_grid.adapters import workers as wk


def _hammer(root, spawnid, task, iterations):
    for _ in range(iterations):
        wk.set_task(root, spawnid, task)


def _hammer_set_task(root, spawnid, task, iterations):
    for _ in range(iterations):
        wk.set_task(root, spawnid, task)


def _hammer_mark_checked(root, spawnid, iterations):
    for _ in range(iterations):
        wk.mark_checked(root, spawnid)


class TestRegistryConcurrency(unittest.TestCase):
    def test_concurrent_set_task_never_clobbers_another_workers_task(self):
        root = tempfile.mkdtemp()
        (Path(root) / "logs").mkdir()
        n = 12
        wk.write_workers(
            root, [{"spawnid": "w%d" % i, "role": "coder", "pid": 1, "task": None} for i in range(n)]
        )

        procs = [
            multiprocessing.Process(target=_hammer, args=(root, "w%d" % i, "t%d" % i, 40))
            for i in range(n)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join()

        final = {w["spawnid"]: w["task"] for w in json.loads((Path(root) / "logs" / "workers.json").read_text())}
        self.assertEqual(len(final), n)
        for i in range(n):
            self.assertEqual(final["w%d" % i], "t%d" % i, "worker w%d lost its task (registry race)" % i)

    def test_concurrent_mark_checked_and_set_task_never_lose_updates(self):
        root = tempfile.mkdtemp()
        (Path(root) / "logs").mkdir()
        n = 12
        wk.write_workers(
            root,
            [{"spawnid": "w%d" % i, "role": "coder", "pid": 1, "task": None, "checked": False} for i in range(n)],
        )

        procs = []
        for i in range(n):
            spawnid = "w%d" % i
            procs.append(multiprocessing.Process(target=_hammer_set_task, args=(root, spawnid, "t%d" % i, 40)))
            procs.append(multiprocessing.Process(target=_hammer_mark_checked, args=(root, spawnid, 40)))
        for p in procs:
            p.start()
        for p in procs:
            p.join()

        final = {w["spawnid"]: w for w in json.loads((Path(root) / "logs" / "workers.json").read_text())}
        self.assertEqual(len(final), n)
        for i in range(n):
            spawnid = "w%d" % i
            self.assertEqual(final[spawnid]["task"], "t%d" % i, "worker %s lost its task (registry race)" % spawnid)
            self.assertTrue(final[spawnid]["checked"], "worker %s lost its checked flag (registry race)" % spawnid)


if __name__ == "__main__":
    unittest.main()
