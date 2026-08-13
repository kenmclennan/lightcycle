import unittest

from lightcycle.application.pool import (
    AcquireRunLockUseCase,
    PoolRunningUseCase,
    ReleaseRunLockUseCase,
)


class FakeLock:
    def __init__(self, acquire_result=(True, 123), running=False):
        self._acquire_result = acquire_result
        self._running = running
        self.released = False

    def acquire(self):
        return self._acquire_result

    def release(self):
        self.released = True

    def is_running(self):
        return self._running


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


class TestPoolRunningUseCase(unittest.TestCase):
    def test_reports_running_when_lock_reports_running(self):
        resp = PoolRunningUseCase(FakeLock(running=True)).execute()
        self.assertTrue(resp.running)

    def test_reports_not_running_when_lock_reports_not_running(self):
        resp = PoolRunningUseCase(FakeLock(running=False)).execute()
        self.assertFalse(resp.running)


if __name__ == "__main__":
    unittest.main()
