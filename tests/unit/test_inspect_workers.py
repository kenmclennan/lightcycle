import unittest

from the_grid.application.inspect import ListWorkers, ResolveLog, Trace
from tests.support.fake_store import FakeStore


class FakeWorkers:
    def __init__(self, workers=None, alive_pids=()):
        self._workers = workers or []
        self._alive = set(alive_pids)

    def workers_state(self):
        return self._workers

    def pid_alive(self, pid):
        return pid in self._alive


class FakeConfig:
    def __init__(self, root="/grid"):
        self._root = root

    def grid_root(self):
        return self._root


class TestListWorkers(unittest.TestCase):
    def test_marks_liveness(self):
        workers = FakeWorkers(workers=[{"role": "coder", "pid": 1}, {"role": "reviewer", "pid": 2}],
                              alive_pids={1})
        rows = ListWorkers(workers).execute()
        self.assertEqual([r["alive"] for r in rows], [True, False])


class TestResolveLog(unittest.TestCase):
    def test_run_target(self):
        path = ResolveLog(FakeWorkers(), FakeConfig("/grid")).execute("run")
        self.assertEqual(path, "/grid/logs/run.log")

    def test_by_bead_or_role_most_recent_wins(self):
        workers = FakeWorkers(workers=[
            {"role": "coder", "bead": "b1", "log": "/l/old.log"},
            {"role": "coder", "bead": "b2", "log": "/l/new.log"},
        ])
        self.assertEqual(ResolveLog(workers, FakeConfig()).execute("b1"), "/l/old.log")
        self.assertEqual(ResolveLog(workers, FakeConfig()).execute("coder"), "/l/new.log")

    def test_unknown_target_is_none(self):
        self.assertIsNone(ResolveLog(FakeWorkers(), FakeConfig()).execute("nope"))


class TestTrace(unittest.TestCase):
    def test_assembles_story_artifacts_tasks_and_logs(self):
        s = FakeStore()
        sid = s.create_story("st")
        s.add_artifact(sid, "spec", "specs/x.md")
        k = s.create_task("build: x", step="build", role="coder", parent=sid)
        workers = FakeWorkers(workers=[{"role": "coder", "bead": k, "log": "/l/k.log"}])
        out = Trace(s, workers).execute(sid)
        self.assertEqual(out["story"]["id"], sid)
        self.assertEqual(out["artifacts"][0]["type"], "spec")
        self.assertEqual(out["tasks"][0]["id"], k)
        self.assertEqual(out["tasks"][0]["log"], "/l/k.log")


if __name__ == "__main__":
    unittest.main()
