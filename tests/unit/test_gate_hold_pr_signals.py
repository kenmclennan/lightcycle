import unittest

from lightcycle.domain.work import State
from tests.support.fake_github import FakeGitHub
from tests.support.stacked import build_stack, with_state
from tests.unit import test_detect_head_moved as head_moved
from tests.unit import test_detect_stack_shape as stack_shape
from tests.unit import test_dispatch_pr_feedback as feedback
from tests.unit.test_gate_hold_watchers import _held_lines, _hold, _release


class TestConflictHeld(unittest.TestCase):
    def test_a_conflict_on_a_held_gate_is_noted_once_and_not_routed(self):
        url = "https://github.com/x/y/pull/911"
        store, item, step, _, uc = feedback.TestMonitorPrsConflict()._setup(
            url, FakeGitHub(conflicted_prs={url}))
        _hold(store, step)

        first = uc.execute()
        notes = store.get_node(step).notes
        uc.execute()

        self.assertEqual(first.conflicted, [])
        self.assertNotEqual(store.get_node(step).state, State.DONE)
        self.assertEqual(
            [l.split(" (x")[0] for l in _held_lines(store, step)],
            ["held: PR conflicts with the base branch (would route to fix-step)"])
        self.assertEqual(store.get_node(step).notes, notes)
        self.assertEqual(len(store.all_nodes()), 2)

    def test_release_lets_the_next_tick_route_the_conflict(self):
        url = "https://github.com/x/y/pull/912"
        store, item, step, _, uc = feedback.TestMonitorPrsConflict()._setup(
            url, FakeGitHub(conflicted_prs={url}))
        _hold(store, step)
        uc.execute()

        _release(store, step)
        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).outcome, "conflicted")
        self.assertEqual(_held_lines(store, step), [])


class TestFeedbackHeld(unittest.TestCase):
    def _case(self):
        url = "https://github.com/x/y/pull/921"
        case = feedback.TestMonitorPrsFeedback()
        gh = FakeGitHub(
            push_time=1000.0, timed_comments=[case._mention_comment(1500.0)])
        return case._setup(url, gh), case

    def test_feedback_on_a_held_gate_opens_nothing_and_notes_once(self):
        (store, item, step, _, uc), case = self._case()
        _hold(store, step)

        first = uc.execute()
        notes = store.get_node(step).notes
        uc.execute()

        self.assertEqual(first.reworked, [])
        self.assertEqual(case._spawned_feedback_steps(store, step), [])
        self.assertIsNone(store.current_run(item, None).comments_dispatched_through)
        self.assertEqual(
            [l.split(" (x")[0] for l in _held_lines(store, step)],
            ["held: PR has outstanding feedback (would open handle-feedback)"])
        self.assertEqual(store.get_node(step).notes, notes)

    def test_release_lets_the_next_tick_open_the_feedback_step(self):
        (store, item, step, _, uc), case = self._case()
        _hold(store, step)
        uc.execute()

        _release(store, step)
        result = uc.execute()

        self.assertEqual(result.reworked, [item])
        self.assertEqual(len(case._spawned_feedback_steps(store, step)), 1)
        self.assertEqual(_held_lines(store, step), [])


class TestHeadMovedHeld(unittest.TestCase):
    def _moved(self):
        url = head_moved._pr(931)
        h = head_moved._Harness({url: "bbb"})
        item = h.item_with_pr(url)
        h.ci_round(item, "passed", "aaa")
        return h, item, h.gate(item)

    def test_a_moved_head_on_a_held_gate_is_noted_once_and_not_routed(self):
        h, item, gate = self._moved()
        _hold(h.store, gate)

        first = h.run()
        notes = h.store.get_node(gate).notes
        h.run()

        self.assertEqual(first.head_moved, [])
        self.assertNotEqual(h.state(gate), "done")
        self.assertEqual(
            [l.split(" (x")[0] for l in _held_lines(h.store, gate)],
            ["held: PR head moved (would route to ci-step)"])
        self.assertEqual(h.store.get_node(gate).notes, notes)

    def test_release_lets_the_next_tick_route_the_move(self):
        h, item, gate = self._moved()
        _hold(h.store, gate)
        h.run()

        _release(h.store, gate)
        result = h.run()

        self.assertEqual(result.head_moved, [item])
        self.assertEqual(_held_lines(h.store, gate), [])

    def test_a_held_gate_with_no_baseline_still_records_one(self):
        url = head_moved._pr(932)
        h = head_moved._Harness({url: "aaa"})
        item = h.item_with_pr(url)
        gate = h.store.create_step(stage="watch-step", role="human", item=item)
        _hold(h.store, gate)

        h.run()
        h.github._head_shas[url] = "bbb"
        h.run()

        self.assertEqual(head_moved._value(h.store, gate, head_moved.PR_HEAD_SHA), "aaa")
        _release(h.store, gate)
        self.assertEqual(h.run().head_moved, [item])


class TestHeadMovedHeldOverAStack(unittest.TestCase):
    def _pushed(self):
        h = head_moved._StackedHarness()
        h.sign(2, "sha-2", "before")
        h.run()
        h.move(2, "sha-2-pushed")
        h.sign(2, "sha-2-pushed", "after")
        return h

    def test_a_pushed_layer_on_a_held_gate_is_noted_once_and_not_routed(self):
        h = self._pushed()
        _hold(h.store, h.gate)
        before = head_moved._value(h.store, h.gate, "pr-layer-heads")

        first = h.run()
        notes = h.store.get_node(h.gate).notes
        h.run()

        self.assertEqual(first.head_moved, [])
        self.assertNotEqual(h.base.state(h.gate), "done")
        self.assertEqual(len(_held_lines(h.store, h.gate)), 1)
        self.assertTrue(_held_lines(h.store, h.gate)[0].startswith("held: PR head moved (would route to "))
        self.assertEqual(h.store.get_node(h.gate).notes, notes)
        self.assertEqual(head_moved._value(h.store, h.gate, "pr-layer-heads"), before)

    def test_release_lets_the_next_tick_route_the_push(self):
        h = self._pushed()
        _hold(h.store, h.gate)
        h.run()

        _release(h.store, h.gate)
        result = h.run()

        self.assertEqual(result.head_moved, [h.item])
        self.assertEqual(_held_lines(h.store, h.gate), [])


class TestStackShapeHeld(unittest.TestCase):
    def _changed(self):
        rig = stack_shape._Rig(build_stack(3))
        rig.tick()
        rig.change(with_state(rig.layers, 2, "closed"))
        return rig

    def test_a_shape_change_on_a_held_gate_is_noted_once_and_not_routed(self):
        rig = self._changed()
        _hold(rig.store, rig.step)
        seen = rig.store.get_run(rig.rid).stack_seen

        first = rig.tick()
        notes = rig.notes()
        rig.tick()

        self.assertEqual(first.shape_changed, [])
        self.assertNotEqual(rig.store.get_node(rig.step).state, State.DONE)
        self.assertEqual(rig.store.get_run(rig.rid).stack_seen, seen)
        self.assertEqual(
            [l.split(" (x")[0] for l in _held_lines(rig.store, rig.step)],
            ["held: stack shape changed (would route to review-stack)"])
        self.assertEqual(rig.notes(), notes)

    def test_release_lets_the_next_tick_route_the_change(self):
        rig = self._changed()
        _hold(rig.store, rig.step)
        rig.tick()

        _release(rig.store, rig.step)
        result = rig.tick()

        self.assertEqual(result.shape_changed, [rig.item])
        self.assertEqual(_held_lines(rig.store, rig.step), [])
