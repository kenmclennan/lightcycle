import unittest

from lightcycle.domain.work import State, derive_state


class DeriveStepStateTest(unittest.TestCase):
    def test_closed_step_is_done(self):
        s = derive_state("step", closed=True, assignee="w1", has_unresolved_deps=True, child_states=[])
        self.assertEqual(s, State.DONE)

    def test_assigned_step_is_in_progress(self):
        s = derive_state("step", closed=False, assignee="w1", has_unresolved_deps=True, child_states=[])
        self.assertEqual(s, State.IN_PROGRESS)

    def test_unresolved_deps_step_is_backlogged(self):
        s = derive_state("step", closed=False, assignee=None, has_unresolved_deps=True, child_states=[])
        self.assertEqual(s, State.BACKLOGGED)

    def test_unblocked_unassigned_step_is_ready(self):
        s = derive_state("step", closed=False, assignee=None, has_unresolved_deps=False, child_states=[])
        self.assertEqual(s, State.READY)


class DeriveContainerStateTest(unittest.TestCase):
    def _item(self, child_states):
        return derive_state("item", closed=False, assignee=None, has_unresolved_deps=False, child_states=child_states)

    def test_all_children_done_is_done(self):
        self.assertEqual(self._item([State.DONE, State.DONE]), State.DONE)

    def test_some_children_done_is_in_progress(self):
        self.assertEqual(self._item([State.DONE, State.READY]), State.IN_PROGRESS)

    def test_some_children_in_progress_is_in_progress(self):
        self.assertEqual(self._item([State.IN_PROGRESS, State.READY]), State.IN_PROGRESS)

    def test_all_children_ready_is_ready(self):
        self.assertEqual(self._item([State.READY, State.READY]), State.READY)

    def test_empty_container_is_backlogged(self):
        self.assertEqual(self._item([]), State.BACKLOGGED)

    def test_closed_container_is_done_regardless_of_children(self):
        s = derive_state("item", closed=True, assignee=None, has_unresolved_deps=False, child_states=[])
        self.assertEqual(s, State.DONE)

    def test_theme_rolls_up_like_item(self):
        s = derive_state("theme", closed=False, assignee=None, has_unresolved_deps=False, child_states=[State.DONE])
        self.assertEqual(s, State.DONE)


if __name__ == "__main__":
    unittest.main()
