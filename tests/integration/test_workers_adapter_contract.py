import shutil
import subprocess
import sys
import tempfile
import unittest

from lightcycle.adapters.workers import WorkersAdapter
from lightcycle.config import Config
from tests.support.workers_contract import WorkersContractBase


class TestWorkersAdapterContract(WorkersContractBase, unittest.TestCase):
    def setUp(self):
        self._root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._root, ignore_errors=True)

        self._alive_proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        self.addCleanup(self._stop_alive_proc)

        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait(timeout=5)
        self._dead_pid = dead.pid

    def _stop_alive_proc(self):
        try:
            self._alive_proc.terminate()
        except ProcessLookupError:
            pass
        try:
            self._alive_proc.wait(timeout=5)
        except Exception:
            pass

    def make_workers(self):
        config = Config(environ={"LC_HOME": self._root})
        w = WorkersAdapter(config)
        w.write_workers([
            {"spawnid": "_alive_seed", "pid": self._alive_proc.pid, "step": None},
            {"spawnid": "_dead_seed", "pid": self._dead_pid, "step": None},
        ])
        return w


if __name__ == "__main__":
    unittest.main()
