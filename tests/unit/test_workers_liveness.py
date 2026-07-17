import unittest

from lightcycle.adapters.workers import decide_alive

_T0 = "Thu Jul  9 09:00:00 2026"
_T1 = "Thu Jul  9 09:05:00 2026"


class TestDecideAlive(unittest.TestCase):
    def test_dead_when_pid_does_not_exist(self):
        self.assertFalse(decide_alive(False, _T0, _T0))

    def test_dead_when_start_time_confirms_a_reused_pid(self):
        self.assertFalse(decide_alive(True, _T0, _T1))

    def test_alive_when_pid_exists_and_start_time_matches(self):
        self.assertTrue(decide_alive(True, _T0, _T0))

    def test_alive_when_no_start_time_was_recorded_since_the_pid_still_exists(self):
        self.assertTrue(decide_alive(True, None, _T0))

    def test_alive_when_the_live_start_time_cannot_be_read_but_the_pid_exists(self):
        self.assertTrue(decide_alive(True, _T0, None))


if __name__ == "__main__":
    unittest.main()
