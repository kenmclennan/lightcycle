import unittest
from unittest.mock import patch

from lightcycle.adapters.workers import kill

_OWN_PGID = 1000


class TestKillProcessGroup(unittest.TestCase):
    def test_kills_the_targets_own_group_when_distinct_from_the_callers(self):
        with patch("os.getpgid", side_effect=lambda pid: _OWN_PGID if pid == 0 else 2000), \
             patch("os.killpg") as killpg, \
             patch("os.kill") as os_kill:
            kill(4242)
        killpg.assert_called_once_with(2000, 15)
        os_kill.assert_not_called()

    def test_falls_back_to_direct_kill_when_the_targets_group_is_the_callers_own(self):
        with patch("os.getpgid", return_value=_OWN_PGID), \
             patch("os.killpg") as killpg, \
             patch("os.kill") as os_kill:
            kill(4242)
        killpg.assert_not_called()
        os_kill.assert_called_once_with(4242, 15)

    def test_falls_back_to_direct_kill_when_getpgid_raises_for_an_already_dead_pid(self):
        def getpgid(pid):
            if pid == 0:
                return _OWN_PGID
            raise ProcessLookupError()

        with patch("os.getpgid", side_effect=getpgid), \
             patch("os.killpg") as killpg, \
             patch("os.kill") as os_kill:
            kill(4242)
        killpg.assert_not_called()
        os_kill.assert_called_once_with(4242, 15)

    def test_never_raises_when_killpg_itself_fails(self):
        with patch("os.getpgid", side_effect=lambda pid: _OWN_PGID if pid == 0 else 2000), \
             patch("os.killpg", side_effect=OSError()):
            kill(4242)


if __name__ == "__main__":
    unittest.main()
