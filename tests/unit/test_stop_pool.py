import unittest

from lightcycle.application.pool import StopPoolUseCase, SweepUseCase
from lightcycle.domain.work import State
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers


class _Git:
    def __init__(self, dirty=False, readable=True):
        self.dirty = dirty
        self.readable = readable
        self.committed = []

    def is_git_repo(self, path):
        return True

    def has_uncommitted(self, path):
        return self.dirty

    def commit_all(self, path, message):
        self.committed.append((path, message))
        return True


class _Worktrees:
    def has_repo(self, item):
        return True

    def worktree_path(self, item):
        return "/tmp/wt/%s" % item


class TestStopPool(unittest.TestCase):
    def _pool(self, *, dirty=False):
        store = FakeStore()
        item = store.create_item("an item", "a description")
        step = store.create_step("build: x", step="build", role="agent", parent=item)
        store.assign(step, "spawn-1")
        store.update_state(step, State.IN_PROGRESS)
        workers = FakeWorkers(alive_pids=(4242,))
        workers.write_workers([
            {"spawnid": "spawn-1", "pid": 4242, "step": step, "started": 0, "role": "agent"}
        ])
        git = _Git(dirty=dirty)
        sweep = SweepUseCase(store, workers, worktrees=_Worktrees(), git=git, fs=None)
        return store, workers, git, step, StopPoolUseCase(workers, sweep)

    def test_a_live_worker_is_stopped(self):
        store, workers, _git, _step, uc = self._pool()
        resp = uc.execute(now=100.0, max_boot=120, stall_seconds=1800)
        self.assertEqual(resp.stopped, ["spawn-1"])
        self.assertIn(4242, workers.killed)

    def test_the_step_it_held_is_reclaimed_so_the_board_is_not_lying(self):
        store, _workers, _git, step, uc = self._pool()
        resp = uc.execute(now=100.0, max_boot=120, stall_seconds=1800)
        self.assertEqual(resp.reclaimed, [step])
        after = store.get_step(step)
        self.assertEqual(after.state, State.READY)
        self.assertFalse(after.claimed_by)

    def test_uncommitted_work_is_preserved_before_the_step_is_reclaimed(self):
        store, _workers, git, step, uc = self._pool(dirty=True)
        resp = uc.execute(now=100.0, max_boot=120, stall_seconds=1800)
        self.assertEqual(resp.preserved, [step])
        self.assertEqual(len(git.committed), 1)
        self.assertIn("preserved", git.committed[0][1])

    def test_stopping_an_idle_pool_stops_and_reclaims_nothing(self):
        store = FakeStore()
        workers = FakeWorkers()
        sweep = SweepUseCase(store, workers)
        resp = StopPoolUseCase(workers, sweep).execute(100.0, 120, 1800)
        self.assertEqual((resp.stopped, resp.reclaimed), ([], []))


if __name__ == "__main__":
    unittest.main()


class TestNoUserFacingOutputNamesThePreRebrandTool(unittest.TestCase):
    def test_no_string_literal_in_the_engine_says_tg(self):
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "lightcycle"
        offenders = []
        for path in sorted(root.rglob("*.py")):
            for n, line in enumerate(path.read_text().splitlines(), 1):
                for literal in re.findall(r'"([^"]*)"|\'([^\']*)\'', line):
                    text = literal[0] or literal[1]
                    if re.search(r"\btg\b", text):
                        offenders.append("%s:%d %s" % (path.name, n, text[:60]))
        self.assertEqual(offenders, [])
