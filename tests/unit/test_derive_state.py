import unittest

from lightcycle.domain.work import State, derive_state, item_blocked_by, role_state


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

    def test_all_children_done_is_backlogged(self):
        self.assertEqual(self._item([State.DONE, State.DONE]), State.BACKLOGGED)

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
            child_states=[State.QUEUED],
        )
        self.assertEqual(s, State.QUEUED)

    def test_items_own_unresolved_dep_outranks_its_childrens_rollup(self):
        s = self._item([State.DONE, State.RUNNING, State.QUEUED], has_unresolved_deps=True)
        self.assertEqual(s, State.BLOCKED)


class RoleStateTest(unittest.TestCase):
    def test_no_role_is_waiting(self):
        self.assertEqual(role_state(None), State.WAITING)

    def test_human_role_is_waiting(self):
        self.assertEqual(role_state("human"), State.WAITING)

    def test_agent_role_is_queued(self):
        self.assertEqual(role_state("agent"), State.QUEUED)

    def test_any_other_role_is_queued(self):
        self.assertEqual(role_state("reviewer"), State.QUEUED)


class ItemBlockedByTest(unittest.TestCase):
    def test_own_blockers_only_when_children_are_not_blocked(self):
        self.assertEqual(
            item_blocked_by("I", ["B"], State.RUNNING, [("I.1", ["X"])]), ["B"]
        )

    def test_step_blockers_listed_when_rolled_up_state_is_blocked(self):
        self.assertEqual(item_blocked_by("I", [], State.BLOCKED, [("I.1", ["B"])]), ["B"])

    def test_running_item_lists_nothing_from_a_gated_sibling_step(self):
        self.assertEqual(item_blocked_by("I", [], State.RUNNING, [("I.2", ["B"])]), [])
        self.assertEqual(item_blocked_by("I", [], State.QUEUED, [("I.2", ["B"])]), [])

    def test_excludes_the_item_itself_and_its_own_steps(self):
        self.assertEqual(
            item_blocked_by("I", [], State.BLOCKED, [("I.2", ["I", "I.1", "B"]), ("I.1", [])]),
            ["B"],
        )

    def test_a_step_gated_only_on_the_item_lists_nothing(self):
        self.assertEqual(item_blocked_by("I", [], State.BLOCKED, [("I.2", ["I"])]), [])

    def test_own_and_step_blockers_naming_the_same_id_appear_once(self):
        self.assertEqual(
            item_blocked_by("I", ["B"], State.BLOCKED, [("I.1", ["B"])]), ["B"]
        )

    def test_output_is_sorted(self):
        self.assertEqual(
            item_blocked_by("I", ["Z"], State.BLOCKED, [("I.1", ["M"]), ("I.2", ["A"])]),
            ["A", "M", "Z"],
        )



if __name__ == "__main__":
    unittest.main()
