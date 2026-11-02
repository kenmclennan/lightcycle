import time
import unittest
from unittest import mock

from lightcycle.application.pool.dispatch_pr_feedback import DispatchPrFeedbackUseCase
from lightcycle.application.pool.pr_poll import PrPoll
from lightcycle.application.pool.pr_snapshot import PrEntry, PrSnapshot
from lightcycle.application.pool.pr_writes import PrWrites
from lightcycle.ports.github import Comment
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_dispatch_pr_feedback import _FEEDBACK_FLOW, _FlowAdapter, plant_pr

_FIRST = "https://github.com/acme/code/pull/1"
_SECOND = "https://github.com/acme/code/pull/2"
_OTHER_REPO = "https://github.com/acme/other/pull/3"
_PREFIX = "pr-feedback:"


class _Log:
    def append_run_log(self, text):
        pass


def _mention(ts):
    return (ts, Comment(author="reviewer", body="@lc fix this", is_top_level=True,
                        id=str(ts), created_at=ts))


class _Epoch:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value


class _Rig:
    def __init__(self, prs, comments=(), **fake):
        self.github = FakeGitHub(
            updated_ats={pr: 1.0 for pr in prs}, head_shas={pr: "h-" + pr[-1] for pr in prs},
            push_time=1000.0, timed_comments=list(comments), **fake)
        self.snapshot = PrSnapshot(self.github)
        self.poll = PrPoll(self.github, self.snapshot, PrWrites(time.monotonic), _Log())
        self.store = FakeStore()
        self.epoch = _Epoch()
        self.now = 0.0
        self.dispatch = DispatchPrFeedbackUseCase(
            self.store, self.snapshot, _FlowAdapter(_FEEDBACK_FLOW), None,
            trusted_authors=lambda: frozenset({"reviewer"}), held_shortcode=lambda: "HLD",
            poll_epoch=self.epoch, unread_note_polls=lambda: 3)

    def gate(self, pr, plant=True):
        item = self.store.create_item("feature", "d")
        if plant:
            plant_pr(self.store, item, pr)
        step = self.store.create_step(stage="ready-merge", role="human", item=item)
        return item, step

    def poll_once(self, *prs):
        for pr in prs:
            self.snapshot.head_sha(pr)
        self.now += 60.0
        self.poll.run(self.snapshot.take_wanted(), self.now, 10)

    def notes(self, step):
        return self.store.get_node(step).notes or ""

    def conditions(self, step):
        return [line for line in self.notes(step).splitlines() if line.startswith(_PREFIX)]

    def feedback_steps(self, item):
        return [s for s in self.store.children(item) if s.stage == "handle-feedback"]


class TestPollFillsAPrWhenTheRepoListingFails(unittest.TestCase):
    def _rig_with_cutoff(self, failing):
        rig = _Rig([_FIRST, _SECOND], comments=[_mention(1500.0)])
        rig.poll_once(_FIRST)
        self.assertIsNotNone(rig.snapshot.entry_of(_FIRST).push_time)
        rig.github._failing_calls.add(failing)
        return rig

    def _assert_second_pr_is_filled_and_dispatched(self, failing):
        rig = self._rig_with_cutoff(failing)
        item, step = rig.gate(_SECOND)

        rig.poll_once(_SECOND)
        rig.poll_once(_SECOND)

        self.assertEqual(rig.snapshot.entry_of(_SECOND).push_time, 1000.0)
        rig.dispatch.execute()
        self.assertEqual(len(rig.feedback_steps(item)), 1)

    def test_a_failing_list_prs_still_fills_a_pr_first_requested_after_the_cutoff(self):
        self._assert_second_pr_is_filled_and_dispatched("list_prs")

    def test_a_failing_repo_inline_comments_still_fills_the_pr(self):
        self._assert_second_pr_is_filled_and_dispatched("repo_inline_comments")

    def test_a_pr_in_a_repo_with_no_cutoff_is_filled_in_the_first_cycle(self):
        rig = _Rig([_FIRST, _OTHER_REPO])
        rig.poll_once(_FIRST)
        rig.github._failing_calls.add("list_prs")

        rig.poll_once(_OTHER_REPO)

        self.assertEqual(rig.snapshot.entry_of(_OTHER_REPO).push_time, 1000.0)

    def test_a_filled_pr_is_not_reread_while_the_listing_fails(self):
        rig = self._rig_with_cutoff("list_prs")
        rig.poll_once(_FIRST)
        before = [c for c in rig.github.calls if c == ("pr_view", _FIRST)]

        rig.poll_once(_FIRST)

        after = [c for c in rig.github.calls if c == ("pr_view", _FIRST)]
        self.assertEqual(len(after), len(before))

    def test_a_pr_whose_full_read_also_fails_stays_stale(self):
        rig = self._rig_with_cutoff("list_prs")
        rig.github._failing_prs.add(_SECOND)

        rig.poll_once(_SECOND)

        self.assertTrue(rig.snapshot.is_stale(_SECOND))
        self.assertIsNone(rig.snapshot.entry_of(_SECOND).push_time)


class TestSilentSkipsRecordACondition(unittest.TestCase):
    def _unread_rig(self):
        rig = _Rig([_FIRST])
        item, step = rig.gate(_FIRST)
        return rig, item, step

    def _run_epochs(self, rig, epochs):
        for e in epochs:
            rig.epoch.value = e
            rig.dispatch.execute()

    def test_unread_last_push_time_is_noted_exactly_on_the_bound_and_names_only_it(self):
        rig, item, step = self._unread_rig()

        self._run_epochs(rig, [5, 6, 7])
        self.assertEqual(rig.conditions(step), [])
        self._run_epochs(rig, [8])

        lines = rig.conditions(step)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith(
            "pr-feedback: not watching %s - the poll has not read last_push_time yet" % _FIRST))
        self.assertNotIn("comments_since", lines[0])

    def test_ticks_inside_the_interval_leave_the_notes_byte_identical(self):
        rig, item, step = self._unread_rig()
        self._run_epochs(rig, [5, 8])
        written = rig.notes(step)

        self._run_epochs(rig, [8, 9, 10, 10])

        self.assertEqual(rig.notes(step), written)

    def test_the_next_interval_boundary_merges_into_the_same_line(self):
        rig, item, step = self._unread_rig()

        self._run_epochs(rig, [5, 8, 9, 10, 11])

        lines = rig.conditions(step)
        self.assertEqual(len(lines), 1)
        self.assertIn("(x2, last", lines[0])

    def test_only_reviews_unread_names_only_reviews(self):
        rig, item, step = self._unread_rig()
        rig.snapshot.publish(_FIRST, PrEntry(
            state="OPEN", push_time=1000.0, comments=[], pull_comments=[], reviews=None))

        self._run_epochs(rig, [0, 3])

        lines = rig.conditions(step)
        self.assertEqual(len(lines), 1)
        self.assertIn("has not read reviews yet", lines[0])
        self.assertNotIn("comments_since", lines[0])
        self.assertNotIn("last_push_time", lines[0])

    def test_several_unread_reads_are_named_in_order(self):
        rig, item, step = self._unread_rig()
        rig.snapshot.publish(_FIRST, PrEntry(state="OPEN", push_time=1000.0, comments=[]))

        self._run_epochs(rig, [0, 3])

        self.assertIn("has not read pull_comments, reviews yet", rig.conditions(step)[0])

    def test_no_run_is_noted_on_the_bound(self):
        rig = _Rig([_FIRST])
        item, step = rig.gate(_FIRST, plant=False)

        self._run_epochs(rig, [5, 7])
        self.assertEqual(rig.conditions(step), [])
        self._run_epochs(rig, [8, 9, 10])

        lines = rig.conditions(step)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith(
            "pr-feedback: not watching - the phase run has no pr recorded"))

    def test_a_run_with_no_pr_is_noted(self):
        rig = _Rig([_FIRST])
        item, step = rig.gate(_FIRST, plant=False)
        rig.store.open_pass(item)
        rig.store.open_run(item, rig.store.current_pass(item).id, None)

        self._run_epochs(rig, [0, 3])

        self.assertEqual(len(rig.conditions(step)), 1)
        self.assertIn("no pr recorded", rig.conditions(step)[0])

    def test_a_feedback_step_already_open_is_noted_naming_it(self):
        rig = _Rig([_FIRST], comments=[_mention(1500.0)])
        rig.poll_once(_FIRST)
        item, step = rig.gate(_FIRST)
        rig.dispatch.execute()
        opened = rig.feedback_steps(item)
        self.assertEqual(len(opened), 1)
        rig.store.set_comments_dispatched_through(rig.store.runs_of(item)[0].id, "0")

        self._run_epochs(rig, [5, 7])
        self.assertEqual(rig.conditions(step), [])
        self._run_epochs(rig, [8, 9])

        lines = rig.conditions(step)
        self.assertEqual(len(lines), 1)
        self.assertIn("feedback is waiting on %s - handle-feedback %s is still open"
                      % (_FIRST, opened[0].id), lines[0])
        self._run_epochs(rig, [9, 10])
        self.assertEqual(rig.conditions(step), lines)


class TestConditionsClearOrAreReplaced(unittest.TestCase):
    def test_filling_the_entry_removes_the_line_and_keeps_other_notes(self):
        rig = _Rig([_FIRST])
        item, step = rig.gate(_FIRST)
        rig.store.note_condition(step, "gh read failed while checking outstanding feedback")
        for e in (0, 3):
            rig.epoch.value = e
            rig.dispatch.execute()
        self.assertEqual(len(rig.conditions(step)), 1)

        rig.poll_once(_FIRST)
        rig.epoch.value = 4
        rig.dispatch.execute()

        self.assertEqual(rig.conditions(step), [])
        self.assertIn("gh read failed", rig.notes(step))

    def test_dispatching_removes_the_line(self):
        rig = _Rig([_FIRST], comments=[_mention(1500.0)])
        item, step = rig.gate(_FIRST)
        for e in (0, 3):
            rig.epoch.value = e
            rig.dispatch.execute()
        self.assertEqual(len(rig.conditions(step)), 1)

        rig.poll_once(_FIRST)
        rig.epoch.value = 4
        rig.dispatch.execute()

        self.assertEqual(rig.conditions(step), [])
        self.assertEqual(len(rig.feedback_steps(item)), 1)

    def test_a_changed_reason_replaces_the_older_line(self):
        rig = _Rig([_FIRST])
        item, step = rig.gate(_FIRST)
        for e in (0, 3):
            rig.epoch.value = e
            rig.dispatch.execute()
        rig.snapshot.publish(_FIRST, PrEntry(
            state="OPEN", push_time=1000.0, comments=[], pull_comments=[], reviews=None))

        for e in (4, 7):
            rig.epoch.value = e
            rig.dispatch.execute()

        lines = rig.conditions(step)
        self.assertEqual(len(lines), 1)
        self.assertIn("has not read reviews yet", lines[0])

    def test_a_step_with_no_condition_never_calls_clear(self):
        rig = _Rig([_FIRST])
        item, step = rig.gate(_FIRST)
        rig.poll_once(_FIRST)

        with mock.patch.object(rig.store, "clear_condition") as clear:
            rig.dispatch.execute()
            rig.dispatch.execute()

        clear.assert_not_called()


class TestMixedGates(unittest.TestCase):
    def test_only_the_unread_gate_carries_a_condition_and_only_the_filled_one_dispatches(self):
        rig = _Rig([_FIRST, _OTHER_REPO], comments=[_mention(1500.0)])
        rig.poll_once(_FIRST)
        filled_item, filled = rig.gate(_FIRST)
        unread_item, unread = rig.gate(_OTHER_REPO)

        for e in (0, 3):
            rig.epoch.value = e
            rig.dispatch.execute()

        self.assertEqual(rig.conditions(filled), [])
        self.assertEqual(len(rig.conditions(unread)), 1)
        self.assertEqual(len(rig.feedback_steps(filled_item)), 1)
        self.assertEqual(rig.feedback_steps(unread_item), [])
