import unittest

from lightcycle.domain.work import Lane, State, lane_for, roll_up


class TestLaneFor(unittest.TestCase):
    def test_done_maps_to_done_lane(self):
        self.assertEqual(lane_for(State.DONE), Lane.DONE)

    def test_running_maps_to_active_lane(self):
        self.assertEqual(lane_for(State.RUNNING), Lane.ACTIVE)

    def test_waiting_maps_to_inbox_lane(self):
        self.assertEqual(lane_for(State.WAITING), Lane.INBOX)

    def test_backlogged_maps_to_queue_lane(self):
        self.assertEqual(lane_for(State.BACKLOGGED), Lane.QUEUE)

    def test_blocked_maps_to_queue_lane(self):
        self.assertEqual(lane_for(State.BLOCKED), Lane.QUEUE)

    def test_queued_maps_to_queue_lane(self):
        self.assertEqual(lane_for(State.QUEUED), Lane.QUEUE)

    def test_lane_has_no_blocked_member(self):
        self.assertFalse(hasattr(Lane, "BLOCKED"))


class TestRollUp(unittest.TestCase):
    def test_no_children_is_backlogged(self):
        self.assertEqual(roll_up([]), State.BACKLOGGED)

    def test_all_done_is_done(self):
        self.assertEqual(roll_up([State.DONE, State.DONE]), State.DONE)

    def test_all_queued_is_queued(self):
        self.assertEqual(roll_up([State.QUEUED, State.QUEUED]), State.QUEUED)

    def test_mix_of_done_and_queued_is_queued(self):
        self.assertEqual(roll_up([State.DONE, State.QUEUED]), State.QUEUED)

    def test_mix_of_queued_and_blocked_is_queued(self):
        self.assertEqual(roll_up([State.QUEUED, State.BLOCKED]), State.QUEUED)

    def test_all_blocked_is_blocked(self):
        self.assertEqual(roll_up([State.BLOCKED, State.BLOCKED]), State.BLOCKED)

    def test_precedence_picks_waiting_over_everything_else(self):
        self.assertEqual(
            roll_up([State.BLOCKED, State.QUEUED, State.RUNNING, State.WAITING, State.DONE]),
            State.WAITING,
        )

    def test_precedence_picks_running_when_waiting_absent(self):
        self.assertEqual(
            roll_up([State.BLOCKED, State.QUEUED, State.RUNNING, State.DONE]),
            State.RUNNING,
        )

    def test_precedence_picks_queued_when_waiting_and_running_absent(self):
        self.assertEqual(
            roll_up([State.BLOCKED, State.QUEUED, State.DONE]),
            State.QUEUED,
        )

    def test_precedence_picks_blocked_when_only_blocked_and_done_remain(self):
        self.assertEqual(roll_up([State.BLOCKED, State.DONE]), State.BLOCKED)


if __name__ == "__main__":
    unittest.main()
