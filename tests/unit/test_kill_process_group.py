import signal
import unittest
from unittest.mock import call, patch

from lightcycle.adapters.workers import kill, signal_resume

_OWN_PGID = 1000


class TestKillProcessGroup(unittest.TestCase):
    def test_kills_the_targets_own_group_when_distinct_from_the_callers(self):
        with patch("os.getpgid", side_effect=lambda pid: _OWN_PGID if pid == 0 else 2000), \
             patch("os.killpg") as killpg, \
             patch("os.kill") as os_kill:
            kill(4242)
        killpg.assert_has_calls([call(2000, signal.SIGCONT), call(2000, signal.SIGTERM)])
        self.assertEqual(killpg.call_count, 2)
        os_kill.assert_not_called()

    def test_falls_back_to_direct_kill_when_the_targets_group_is_the_callers_own(self):
        with patch("os.getpgid", return_value=_OWN_PGID), \
             patch("os.killpg") as killpg, \
             patch("os.kill") as os_kill:
            kill(4242)
        killpg.assert_not_called()
        os_kill.assert_has_calls([call(4242, signal.SIGCONT), call(4242, signal.SIGTERM)])
        self.assertEqual(os_kill.call_count, 2)

    def test_kills_via_killpg_using_pid_as_pgid_when_getpgid_raises_for_an_already_dead_pid(self):
        def getpgid(pid):
            if pid == 0:
                return _OWN_PGID
            raise ProcessLookupError()

        with patch("os.getpgid", side_effect=getpgid), \
             patch("os.killpg") as killpg, \
             patch("os.kill") as os_kill:
            kill(4242)
        killpg.assert_has_calls([call(4242, signal.SIGCONT), call(4242, signal.SIGTERM)])
        self.assertEqual(killpg.call_count, 2)
        os_kill.assert_not_called()

    def test_never_raises_when_killpg_itself_fails(self):
        with patch("os.getpgid", side_effect=lambda pid: _OWN_PGID if pid == 0 else 2000), \
             patch("os.killpg", side_effect=OSError()):
            kill(4242)

    def test_signal_resume_sends_exactly_sigcont_through_the_guarded_path(self):
        with patch("os.getpgid", side_effect=lambda pid: _OWN_PGID if pid == 0 else 2000), \
             patch("os.killpg") as killpg, \
             patch("os.kill") as os_kill:
            signal_resume(4242)
        killpg.assert_called_once_with(2000, signal.SIGCONT)
        os_kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
