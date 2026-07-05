import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from the_grid.adapters import workers as wk


def _hammer(root, spawnid, task, iterations):
    for _ in range(iterations):
        wk.set_task(root, spawnid, task)


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


if __name__ == "__main__":
    unittest.main()
