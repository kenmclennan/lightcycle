import time
import unittest

from lightcycle.application.pool.pr_poll import PrPoll
from lightcycle.application.pool.pr_snapshot import PrSnapshot
from lightcycle.application.pool.pr_writes import PrWrites
from tests.support.fake_github import FakeGitHub

_ONE = "https://github.com/acme/widget/pull/1"
_TWO = "https://github.com/acme/widget/pull/2"


class _Log:
    def append_run_log(self, text):
        pass


def _poll(github):
    snapshot = PrSnapshot(github)
    return PrPoll(github, snapshot, PrWrites(time.monotonic), _Log()), snapshot


def _round(poll, snapshot, now):
    snapshot.head_sha(_ONE)
    snapshot.head_sha(_TWO)
    poll.run(snapshot.take_wanted(), now, 10)


class TestPrPollConfirmation(unittest.TestCase):
    def test_every_pr_polled_without_failure_is_confirmed(self):
        github = FakeGitHub(updated_ats={_ONE: 1.0, _TWO: 1.0}, head_shas={_ONE: "a", _TWO: "b"})
        poll, snapshot = _poll(github)
        epoch = snapshot.poll_epoch()

        _round(poll, snapshot, 0.0)

        self.assertTrue(snapshot.confirmed_after(_ONE, epoch))
        self.assertTrue(snapshot.confirmed_after(_TWO, epoch))

    def test_a_failing_pr_view_leaves_that_pr_unconfirmed_and_its_sibling_confirmed(self):
        github = FakeGitHub(
            updated_ats={_ONE: 1.0, _TWO: 1.0}, head_shas={_ONE: "a", _TWO: "b"}, failing_prs=[_TWO])
        poll, snapshot = _poll(github)
        epoch = snapshot.poll_epoch()

        _round(poll, snapshot, 0.0)

        self.assertTrue(snapshot.confirmed_after(_ONE, epoch))
        self.assertFalse(snapshot.confirmed_after(_TWO, epoch))

    def test_a_failing_list_prs_leaves_every_pr_unconfirmed(self):
        github = FakeGitHub(updated_ats={_ONE: 1.0, _TWO: 1.0}, head_shas={_ONE: "a", _TWO: "b"})
        poll, snapshot = _poll(github)
        _round(poll, snapshot, 0.0)
        github._failing_calls.add("list_prs")
        epoch = snapshot.poll_epoch()

        _round(poll, snapshot, 60.0)

        self.assertFalse(snapshot.confirmed_after(_ONE, epoch))
        self.assertFalse(snapshot.confirmed_after(_TWO, epoch))


class _MovingBase(FakeGitHub):
    def pr_view(self, pr):
        view = super().pr_view(pr)
        if not self._moved_once:
            self._moved_once = True
            self.advance_base("acme/widget", "main")
            self._conflicted.add(pr)
        return view


class TestPrPollColdStartBaseTips(unittest.TestCase):
    def test_a_base_move_between_the_first_view_and_the_tip_read_is_caught_at_cold_start(self):
        github = _MovingBase(updated_ats={_ONE: 1.0}, head_shas={_ONE: "a"})
        github._moved_once = False
        poll, snapshot = _poll(github)

        _round(poll, snapshot, 0.0)

        self.assertEqual("CONFLICTING", snapshot.entry_of(_ONE).view.mergeable)

    def test_cold_start_reads_one_extra_view_per_base_and_one_tip_per_base(self):
        github = FakeGitHub(updated_ats={_ONE: 1.0, _TWO: 1.0}, head_shas={_ONE: "a", _TWO: "b"})
        poll, snapshot = _poll(github)

        _round(poll, snapshot, 0.0)

        names = [call[0] for call in github.calls]
        self.assertEqual(3, names.count("pr_view"))
        self.assertEqual(1, names.count("branch_tip"))
