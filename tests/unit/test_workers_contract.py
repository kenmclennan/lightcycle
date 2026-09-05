import unittest

from tests.support.fake_workers import FakeWorkers
from tests.support.workers_contract import WorkersContractBase

_ALIVE_PID = 424242001
_DEAD_PID = 424242002


class TestFakeWorkersContract(WorkersContractBase, unittest.TestCase):
    def make_workers(self):
        w = FakeWorkers(alive_pids=[_ALIVE_PID])
        w.write_workers([
            {"spawnid": "_alive_seed", "pid": _ALIVE_PID, "step": None},
            {"spawnid": "_dead_seed", "pid": _DEAD_PID, "step": None},
        ])
        return w


if __name__ == "__main__":
    unittest.main()
