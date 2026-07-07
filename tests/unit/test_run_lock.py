import unittest

from lightcycle.application.pool import AcquireRunLockUseCase, ReleaseRunLockUseCase


class FakeLock:
    def __init__(self, acquire_result=(True, 123)):
        self._acquire_result = acquire_result
        self.released = False

    def acquire(self):
        return self._acquire_result

    def release(self):
        self.released = True


class TestAcquireRunLockUseCase(unittest.TestCase):
    def test_reports_acquired_with_holder_pid(self):
        resp = AcquireRunLockUseCase(FakeLock(acquire_result=(True, 123))).execute()
        self.assertTrue(resp.acquired)
        self.assertEqual(resp.holder_pid, 123)

    def test_reports_refused_with_existing_holder_pid(self):
        resp = AcquireRunLockUseCase(FakeLock(acquire_result=(False, 456))).execute()
        self.assertFalse(resp.acquired)
        self.assertEqual(resp.holder_pid, 456)


class TestReleaseRunLockUseCase(unittest.TestCase):
    def test_releases_the_lock(self):
        lock = FakeLock()
        ReleaseRunLockUseCase(lock).execute()
        self.assertTrue(lock.released)


if __name__ == "__main__":
    unittest.main()
