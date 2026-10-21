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
    poll.run(snapshot.take_wanted(), now)


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
