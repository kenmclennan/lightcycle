import unittest

from lightcycle.domain.work import Lane, State, lane_for, roll_up


class TestLaneFor(unittest.TestCase):
    def test_done_maps_to_done_lane(self):
        self.assertEqual(lane_for(State.DONE, role="coder"), Lane.DONE)

    def test_in_progress_maps_to_active_lane(self):
        self.assertEqual(lane_for(State.IN_PROGRESS, role="coder"), Lane.ACTIVE)

    def test_backlogged_maps_to_blocked_lane(self):
        self.assertEqual(lane_for(State.BACKLOGGED, role="coder"), Lane.BLOCKED)

    def test_ready_with_human_role_maps_to_inbox(self):
        self.assertEqual(lane_for(State.READY, role="human"), Lane.INBOX)

    def test_ready_with_agent_role_maps_to_queue(self):
        self.assertEqual(lane_for(State.READY, role="coder"), Lane.QUEUE)

    def test_ready_with_no_role_maps_to_queue(self):
        self.assertEqual(lane_for(State.READY, role=None), Lane.QUEUE)


class TestRollUp(unittest.TestCase):
    def test_no_children_is_backlogged(self):
        self.assertEqual(roll_up([]), State.BACKLOGGED)

    def test_all_ready_is_ready(self):
        self.assertEqual(roll_up([State.READY, State.READY]), State.READY)

    def test_all_done_is_done(self):
        self.assertEqual(roll_up([State.DONE, State.DONE]), State.DONE)

    def test_any_in_progress_is_in_progress(self):
        self.assertEqual(roll_up([State.READY, State.IN_PROGRESS]), State.IN_PROGRESS)

    def test_mix_of_done_and_not_done_is_in_progress(self):
        self.assertEqual(roll_up([State.DONE, State.READY]), State.IN_PROGRESS)

    def test_mix_of_ready_and_backlogged_is_ready(self):
        self.assertEqual(roll_up([State.READY, State.BACKLOGGED]), State.READY)

    def test_all_backlogged_is_ready(self):
        self.assertEqual(roll_up([State.BACKLOGGED, State.BACKLOGGED]), State.READY)


if __name__ == "__main__":
    unittest.main()
