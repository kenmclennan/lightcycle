import unittest

from lightcycle.application.pool.gh_call_accrual import GhCallAccrualUseCase
from lightcycle.ports.workers import RegistryUnreadable
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.step_factory import create_owned_step

ROOT = "/grid"


class _Config:
    def data_root(self):
        return ROOT


class _UnreadableWorkers(FakeWorkers):
    def workers_state(self):
        raise RegistryUnreadable("boom")


def _line(n):
    return ("1\tsp\t0\tapi repos/o/r/pulls/%d\n" % n).encode()


def _path(spawnid):
    return "%s/logs/gh-calls-%s.log" % (ROOT, spawnid)


def _append(fs, path, text):
    existing, _ = fs.read_from(path, 0)
    fs.write_text(path, existing.decode() + text)


def _worker(spawnid, step):
    return {"spawnid": spawnid, "role": "agent", "pid": 1, "step": step, "log": "/l/x.log",
            "started": 0}


def _usecase(store, fs, workers):
    return GhCallAccrualUseCase(store, fs, workers, _Config())


class TestGhCallAccrual(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.a = create_owned_step(self.store, "a", step="build", role="agent")
        self.b = create_owned_step(self.store, "b", step="build", role="agent")

    def test_only_a_worker_with_a_step_and_a_log_writes_a_count(self):
        fs = FakeFs(files={_path("s1"): _line(1) + _line(2), _path("s3"): _line(1)})
        workers = FakeWorkers(workers=[
            _worker("s1", self.a), _worker("s2", self.b),
            {"spawnid": "s3", "role": "agent", "pid": 3, "step": None, "log": "/l/3.log", "started": 0},
        ])

        _usecase(self.store, fs, workers).execute()

        self.assertEqual(self.store.get_node(self.a).usage_api_calls, 2)
        self.assertIsNone(self.store.get_node(self.b).usage_api_calls)

    def test_a_step_served_by_two_spawns_sums_them_and_a_rerun_writes_nothing_new(self):
        fs = FakeFs(files={_path("s1"): _line(1) * 4, _path("s2"): _line(2) * 3})
        workers = FakeWorkers(workers=[_worker("s1", self.a), _worker("s2", self.a)])
        uc = _usecase(self.store, fs, workers)

        uc.execute()
        uc.execute()

        self.assertEqual(self.store.get_node(self.a).usage_api_calls, 7)

    def test_a_pool_restart_rebuilds_the_same_absolute_counts(self):
        fs = FakeFs(files={_path("s1"): _line(1) * 4})
        workers = FakeWorkers(workers=[_worker("s1", self.a)])
        _usecase(self.store, fs, workers).execute()

        _usecase(self.store, fs, workers).execute()

        self.assertEqual(self.store.get_node(self.a).usage_api_calls, 4)

    def test_growth_between_ticks_is_added_to_the_running_count(self):
        fs = FakeFs(files={_path("s1"): _line(1) * 2})
        workers = FakeWorkers(workers=[_worker("s1", self.a)])
        uc = _usecase(self.store, fs, workers)
        uc.execute()

        _append(fs, _path("s1"), "1\tsp\t0\tapi x\n")
        uc.execute()

        self.assertEqual(self.store.get_node(self.a).usage_api_calls, 3)

    def test_a_partial_last_line_is_not_counted_until_it_completes(self):
        fs = FakeFs(files={_path("s1"): _line(1) + b"1\tsp\t0\tapi par"})
        workers = FakeWorkers(workers=[_worker("s1", self.a)])
        uc = _usecase(self.store, fs, workers)

        uc.execute()
        self.assertEqual(self.store.get_node(self.a).usage_api_calls, 1)

        _append(fs, _path("s1"), "tial\n")
        uc.execute()
        self.assertEqual(self.store.get_node(self.a).usage_api_calls, 2)

    def test_an_unreadable_registry_skips_the_pass(self):
        fs = FakeFs(files={_path("s1"): _line(1)})

        _usecase(self.store, fs, _UnreadableWorkers()).execute()

        self.assertIsNone(self.store.get_node(self.a).usage_api_calls)

    def test_a_dead_workers_last_lines_are_still_counted(self):
        fs = FakeFs(files={_path("s1"): _line(1) * 5})
        workers = FakeWorkers(workers=[_worker("s1", self.a)], alive_pids=())

        _usecase(self.store, fs, workers).execute()

        self.assertEqual(self.store.get_node(self.a).usage_api_calls, 5)


if __name__ == "__main__":
    unittest.main()
