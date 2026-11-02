import unittest

from tests.unit.test_pr_feedback_conditions import _FIRST, _Rig


class TestPollStampsTheReadTime(unittest.TestCase):
    def test_a_full_read_stamps_the_poll_time(self):
        rig = _Rig([_FIRST])

        rig.poll_once(_FIRST)

        self.assertEqual(rig.snapshot.entry_of(_FIRST).read_at, rig.now)

    def test_a_view_refresh_restamps_the_poll_time(self):
        rig = _Rig([_FIRST])
        rig.poll_once(_FIRST)
        first = rig.now

        rig.poll_once(_FIRST)

        self.assertGreater(rig.now, first)
        self.assertEqual(rig.snapshot.entry_of(_FIRST).read_at, rig.now)
