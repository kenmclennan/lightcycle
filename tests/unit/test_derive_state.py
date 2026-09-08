import unittest

from lightcycle.domain.work import State, derive_state


class DeriveStepStateTest(unittest.TestCase):
    def test_closed_step_is_done(self):
        s = derive_state(
            "step", closed=True, assignee="w1", has_unresolved_deps=True, role="human",
            child_states=[],
        )
        self.assertEqual(s, State.DONE)

    def test_assigned_step_is_running(self):
        s = derive_state(
            "step", closed=False, assignee="w1", has_unresolved_deps=True, role="human",
            child_states=[],
        )
        self.assertEqual(s, State.RUNNING)

    def test_unresolved_deps_step_is_blocked(self):
        s = derive_state(
            "step", closed=False, assignee=None, has_unresolved_deps=True, role="agent",
            child_states=[],
        )
        self.assertEqual(s, State.BLOCKED)

    def test_unblocked_unassigned_human_step_is_waiting(self):
        s = derive_state(
            "step", closed=False, assignee=None, has_unresolved_deps=False, role="human",
            child_states=[],
        )
        self.assertEqual(s, State.WAITING)

    def test_unblocked_unassigned_agent_step_is_queued(self):
        s = derive_state(
            "step", closed=False, assignee=None, has_unresolved_deps=False, role="agent",
            child_states=[],
        )
        self.assertEqual(s, State.QUEUED)

    def test_unblocked_unassigned_step_with_no_role_is_waiting(self):
        s = derive_state(
            "step", closed=False, assignee=None, has_unresolved_deps=False, role=None,
            child_states=[],
        )
        self.assertEqual(s, State.WAITING)


class DeriveContainerStateTest(unittest.TestCase):
    def _item(self, child_states, has_unresolved_deps=False):
        return derive_state(
            "item", closed=False, assignee=None, has_unresolved_deps=has_unresolved_deps,
            role=None, child_states=child_states,
        )

    def test_all_children_done_is_done(self):
        self.assertEqual(self._item([State.DONE, State.DONE]), State.DONE)

    def test_some_children_queued_is_queued(self):
        self.assertEqual(self._item([State.DONE, State.QUEUED]), State.QUEUED)

    def test_some_children_running_is_running(self):
        self.assertEqual(self._item([State.RUNNING, State.QUEUED]), State.RUNNING)

    def test_all_children_queued_is_queued(self):
        self.assertEqual(self._item([State.QUEUED, State.QUEUED]), State.QUEUED)

    def test_empty_container_is_backlogged(self):
        self.assertEqual(self._item([]), State.BACKLOGGED)

    def test_closed_container_is_done_regardless_of_children(self):
        s = derive_state(
            "item", closed=True, assignee=None, has_unresolved_deps=False, role=None,
            child_states=[],
        )
        self.assertEqual(s, State.DONE)

    def test_item_rolls_up_from_its_steps(self):
        s = derive_state(
            "item", closed=False, assignee=None, has_unresolved_deps=False, role=None,
            child_states=[State.DONE],
        )
        self.assertEqual(s, State.DONE)

    def test_items_own_unresolved_dep_outranks_its_childrens_rollup(self):
        s = self._item([State.DONE, State.RUNNING, State.QUEUED], has_unresolved_deps=True)
        self.assertEqual(s, State.BLOCKED)


if __name__ == "__main__":
    unittest.main()
