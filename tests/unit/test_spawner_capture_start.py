import unittest

from lightcycle.adapters.spawner import capture_pid_started


class FakeProc:
    def __init__(self, pid, poll_results):
        self.pid = pid
        self._poll_results = list(poll_results)

    def poll(self):
        return self._poll_results.pop(0)


class TestCapturePidStarted(unittest.TestCase):
    def test_retries_while_process_is_still_alive_and_records_start(self):
        starts = iter([None, None, "Thu Jul  9 09:00:00 2026"])
        proc = FakeProc(pid=123, poll_results=[None, None])
        sleeps = []
        result = capture_pid_started(
            proc,
            get_start=lambda pid: next(starts),
            sleep=sleeps.append,
            attempts=5,
        )
        self.assertEqual(result, "Thu Jul  9 09:00:00 2026")
        self.assertEqual(len(sleeps), 2)

    def test_returns_none_when_process_already_exited(self):
        proc = FakeProc(pid=123, poll_results=[0])
        result = capture_pid_started(
            proc,
            get_start=lambda pid: None,
            sleep=lambda interval: None,
            attempts=5,
        )
        self.assertIsNone(result)

    def test_gives_up_after_exhausting_attempts_while_still_alive(self):
        proc = FakeProc(pid=123, poll_results=[None, None])
        result = capture_pid_started(
            proc,
            get_start=lambda pid: None,
            sleep=lambda interval: None,
            attempts=3,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
