import unittest

from lightcycle.application.pool.guidance_sync import GuidanceSyncUseCase
from lightcycle.domain.pool import GuidanceSyncState
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeGuidanceSyncStatus

ROOT = "/kb"


class FakeConfig:
    def guidance_fetch_minutes(self):
        return 5


def _use(git=None, status=None, registered=True, exists=True):
    store = FakeStore()
    if registered:
        store.add_project("guidance", local_path=ROOT)
    fs = FakeFs(dirs={ROOT: []} if exists else {})
    git = git if git is not None else FakeGit(origin="git@x:kb.git", ref="origin/main")
    status = status if status is not None else FakeGuidanceSyncStatus()
    return GuidanceSyncUseCase(store, git, fs, status, FakeConfig()), git, status


def _fetches(git):
    return [c for c in git.calls if c[0] == "fetch_origin"]


class TestGuidanceSync(unittest.TestCase):
    def test_success_records_ok_the_time_and_the_ref(self):
        use, git, status = _use()
        use.execute(1000.0)
        self.assertEqual(len(_fetches(git)), 1)
        self.assertEqual(
            status.load(),
            GuidanceSyncState(ok=True, at=1000.0, detail="", ref="origin/main"))

    def test_failure_records_the_detail_and_does_not_raise(self):
        git = FakeGit(origin="git@x:kb.git", ref="origin/main", fetch_ok=False,
                      fetch_detail="could not resolve host")
        use, _, status = _use(git=git)
        result = use.execute(1000.0)
        self.assertFalse(result.ok)
        self.assertEqual(
            status.load(),
            GuidanceSyncState(ok=False, at=1000.0, detail="could not resolve host", ref=None))

    def test_no_registered_project_makes_no_fetch_and_records_nothing(self):
        use, git, status = _use(registered=False)
        use.execute(1000.0)
        self.assertEqual(_fetches(git), [])
        self.assertIsNone(status.load())

    def test_missing_directory_makes_no_fetch_and_records_nothing(self):
        use, git, status = _use(exists=False)
        use.execute(1000.0)
        self.assertEqual(_fetches(git), [])
        self.assertIsNone(status.load())

    def test_no_origin_remote_makes_no_fetch_and_records_nothing(self):
        use, git, status = _use(git=FakeGit(origin=None, ref="main"))
        use.execute(1000.0)
        self.assertEqual(_fetches(git), [])
        self.assertIsNone(status.load())

    def test_inside_the_interval_makes_no_fetch_and_leaves_the_record(self):
        record = GuidanceSyncState(ok=True, at=1000.0, detail="", ref="origin/main")
        use, git, status = _use(status=FakeGuidanceSyncStatus(record))
        use.execute(1240.0)
        self.assertEqual(_fetches(git), [])
        self.assertEqual(status.load(), record)

    def test_exactly_at_the_interval_fetches(self):
        use, git, status = _use(status=FakeGuidanceSyncStatus(
            GuidanceSyncState(ok=True, at=1000.0, detail="", ref="origin/main")))
        use.execute(1300.0)
        self.assertEqual(len(_fetches(git)), 1)
        self.assertEqual(status.load().at, 1300.0)

    def test_a_failed_attempt_waits_the_full_interval(self):
        failed = GuidanceSyncState(ok=False, at=1000.0, detail="boom", ref=None)
        use, git, status = _use(status=FakeGuidanceSyncStatus(failed))
        use.execute(1100.0)
        self.assertEqual(_fetches(git), [])
        self.assertEqual(status.load(), failed)
        use.execute(1300.0)
        self.assertEqual(len(_fetches(git)), 1)


if __name__ == "__main__":
    unittest.main()
