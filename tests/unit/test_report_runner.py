import datetime
import threading
import unittest

from lightcycle.adapters.report_runner import ReportRunner
from lightcycle.application.work.report import ReportInput, ReportUseCase
from tests.support.fake_store import FakeStore


DAY = datetime.date(2026, 10, 23)


class _ClosableStore(FakeStore):
    def __init__(self):
        super().__init__()
        self.closed_on = None
        self.built_on = threading.get_ident()

    def close(self):
        self.closed_on = threading.get_ident()


class TestReportRunner(unittest.TestCase):
    def _runner(self):
        built = []

        def build():
            store = _ClosableStore()
            built.append(store)
            return store

        runner = ReportRunner(build, ReportUseCase)
        self.addCleanup(runner.close)
        return runner, built

    def test_several_runs_build_the_store_once(self):
        runner, built = self._runner()

        for _ in range(4):
            runner.execute(ReportInput(DAY))

        self.assertEqual(len(built), 1)

    def test_every_run_and_the_close_use_the_thread_that_built_the_store(self):
        runner, built = self._runner()
        seen = []

        def run():
            runner.execute(ReportInput(DAY))
            seen.append(built[0].built_on)

        threads = [threading.Thread(target=run) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        runner.close()

        self.assertEqual(len(built), 1)
        self.assertEqual(len(set(seen)), 1)
        self.assertEqual(built[0].closed_on, built[0].built_on)

    def test_close_without_a_run_builds_nothing(self):
        runner, built = self._runner()

        runner.close()

        self.assertEqual(built, [])

    def test_a_run_after_close_is_refused(self):
        runner, _ = self._runner()
        runner.close()

        with self.assertRaises(RuntimeError):
            runner.execute(ReportInput(DAY))
