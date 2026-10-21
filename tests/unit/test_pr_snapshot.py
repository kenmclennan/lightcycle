import unittest

from lightcycle.application.pool.pr_snapshot import PrEntry, PrSnapshot
from lightcycle.ports.github import Comment, NotYetRead, PrView, ReadFailure
from tests.support.fake_github import FakeGitHub

_PR = "https://github.com/acme/widget/pull/1"


def _view(**kw):
    base = dict(
        state="OPEN", head_sha="h1", base_ref="main", base_key="acme/widget@main",
        mergeable="MERGEABLE", merge_state_status="CLEAN", updated_at=1.0)
    base.update(kw)
    return PrView(**base)


class TestUnreadPr(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.snap = PrSnapshot(self.github)

    def test_every_read_is_not_yet_read_and_issues_no_call(self):
        reads = [
            self.snap.is_merged(_PR), self.snap.is_closed_unmerged(_PR),
            self.snap.head_sha(_PR), self.snap.pr_sync_state(_PR),
            self.snap.last_push_time(_PR), self.snap.comments_since(_PR, 0.0),
            self.snap.pull_comments(_PR, 0.0), self.snap.reviews(_PR, 0.0),
            self.snap.changed_files(_PR, "h1"), self.snap.check_runs(_PR, "h1"),
        ]

        for read in reads:
            self.assertIsInstance(read, NotYetRead)
            self.assertIsInstance(read, ReadFailure)
        self.assertEqual(self.github.calls, [])

    def test_required_checks_is_not_yet_read_until_published(self):
        self.assertIsInstance(self.snap.required_checks("acme/widget@main"), NotYetRead)
        self.snap.publish_required("acme/widget@main", frozenset({"build"}))
        self.assertEqual(self.snap.required_checks("acme/widget@main"), frozenset({"build"}))
        self.snap.publish_required("acme/widget@main", None)
        self.assertIsNone(self.snap.required_checks("acme/widget@main"))
        self.assertEqual(self.github.calls, [])

    def test_reads_register_the_pr_and_the_wanted_pairs(self):
        self.snap.pr_sync_state(_PR)
        self.snap.changed_files(_PR, "h1")
        self.snap.check_runs(_PR, "h2")

        wanted = self.snap.take_wanted()

        self.assertEqual(wanted.prs, frozenset([_PR]))
        self.assertEqual(wanted.files, frozenset([(_PR, "h1")]))
        self.assertEqual(wanted.checks, frozenset([_PR]))
        self.assertEqual(self.snap.take_wanted().prs, frozenset())


class TestReadPr(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.snap = PrSnapshot(self.github)
        self.comment = Comment(author="a", body="b", is_top_level=True, created_at=5.0)
        self.snap.publish(_PR, PrEntry(
            state="OPEN", view=_view(mergeable="CONFLICTING", merge_state_status="BEHIND"),
            updated_at=1.0, push_time=3.0, comments=[self.comment], pull_comments=[],
            reviews=[]))

    def test_derives_the_sync_state_from_the_shared_view(self):
        sync = self.snap.pr_sync_state(_PR)

        self.assertTrue(sync.behind)
        self.assertTrue(sync.conflicted)
        self.assertEqual(sync.head_sha, "h1")
        self.assertEqual(sync.base_key, "acme/widget@main")
        self.assertEqual(self.snap.head_sha(_PR), "h1")
        self.assertFalse(self.snap.is_merged(_PR))

    def test_filters_feedback_by_the_readers_own_since(self):
        self.assertEqual(self.snap.comments_since(_PR, 4.0), [self.comment])
        self.assertEqual(self.snap.comments_since(_PR, 5.0), [])
        self.assertEqual(self.snap.last_push_time(_PR), 3.0)
        self.assertEqual(self.github.calls, [])

    def test_a_stale_entry_still_answers_and_reports_stale(self):
        self.snap.mark_stale(_PR)

        self.assertTrue(self.snap.is_stale(_PR))
        self.assertEqual(self.snap.head_sha(_PR), "h1")

    def test_a_pr_never_read_is_not_stale(self):
        self.assertFalse(self.snap.is_stale("https://github.com/acme/widget/pull/9"))

    def test_retain_drops_entries_for_prs_no_longer_wanted(self):
        self.snap.retain(frozenset(), frozenset())

        self.assertIsInstance(self.snap.head_sha(_PR), NotYetRead)

    def test_retain_drops_check_runs_no_ci_step_asked_for(self):
        self.snap.publish_checks(_PR, "h1", ["run"])

        self.snap.retain(frozenset([_PR]), frozenset())

        self.assertIsInstance(self.snap.check_runs(_PR, "h1"), NotYetRead)

    def test_retain_keeps_check_runs_a_ci_step_still_asks_for(self):
        self.snap.publish_checks(_PR, "h1", ["run"])

        self.snap.retain(frozenset([_PR]), frozenset([_PR]))

        self.assertEqual(self.snap.check_runs(_PR, "h1"), ["run"])

    def test_writes_and_login_reach_the_real_port(self):
        self.github._head_shas[_PR] = "h1"
        self.assertEqual(self.snap.authenticated_login(), "operator")
        self.assertIsNone(self.snap.update_branch(_PR, "h1"))
        self.assertEqual(self.github.update_calls, [(_PR, "h1")])


class TestPollEpoch(unittest.TestCase):
    def setUp(self):
        self.snap = PrSnapshot(FakeGitHub())

    def test_take_wanted_advances_the_epoch_and_reports_it(self):
        before = self.snap.poll_epoch()

        wanted = self.snap.take_wanted()

        self.assertEqual(wanted.epoch, before + 1)
        self.assertEqual(self.snap.poll_epoch(), before + 1)

    def test_a_pr_is_confirmed_after_only_epochs_below_its_confirmed_one(self):
        self.snap.confirm([_PR], 3)

        self.assertTrue(self.snap.confirmed_after(_PR, 2))
        self.assertFalse(self.snap.confirmed_after(_PR, 3))
        self.assertFalse(self.snap.confirmed_after(_PR, 4))

    def test_confirming_one_pr_leaves_another_unconfirmed(self):
        other = "https://github.com/acme/widget/pull/2"

        self.snap.confirm([_PR], 5)

        self.assertFalse(self.snap.confirmed_after(other, 0))

    def test_retain_drops_confirmations_of_unwanted_prs(self):
        self.snap.confirm([_PR], 5)

        self.snap.retain(frozenset(), frozenset())

        self.assertFalse(self.snap.confirmed_after(_PR, 0))
