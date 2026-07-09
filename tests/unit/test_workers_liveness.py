import unittest

from lightcycle.adapters.workers import decide_alive


class TestDecideAlive(unittest.TestCase):
    def test_dead_when_pid_does_not_exist(self):
        self.assertFalse(decide_alive(False, "Thu Jul  9 09:00:00 2026", "Thu Jul  9 09:00:00 2026"))

    def test_dead_when_start_time_does_not_match_a_reused_pid(self):
        self.assertFalse(decide_alive(True, "Thu Jul  9 09:00:00 2026", "Thu Jul  9 09:05:00 2026"))

    def test_alive_when_pid_exists_and_start_time_matches(self):
        self.assertTrue(decide_alive(True, "Thu Jul  9 09:00:00 2026", "Thu Jul  9 09:00:00 2026"))

    def test_alive_when_pid_exists_and_no_start_time_was_recorded(self):
        self.assertTrue(decide_alive(True, None, "Thu Jul  9 09:00:00 2026"))


if __name__ == "__main__":
    unittest.main()
