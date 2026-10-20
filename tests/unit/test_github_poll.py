import unittest
import time

from lightcycle.application.pool.github_poll import GithubPollUseCase
from lightcycle.application.pool.pr_snapshot import PrSnapshot
from lightcycle.application.pool.pr_writes import PrWrites
from lightcycle.config import ConfigError
from lightcycle.ports.github import CheckRun, Comment, NotYetRead, RateLimit, ReadFailure
from tests.support.fake_fs import FakeFs
from tests.support.fake_github import FakeGitHub
from tests.support.fake_github_budget_status import FakeGithubBudgetStatus
from tests.support.fake_github_poll_runner import BlockingGithubPollRunner, InlineGithubPollRunner

_A = ["https://github.com/acme/widget/pull/%d" % n for n in range(1, 9)]
_B = ["https://github.com/acme/gadget/pull/%d" % n for n in range(1, 9)]
_ALL = _A + _B
_PER_PR_CALLS = (
    "pr_view", "last_push_time", "comments_since", "pull_comments", "reviews",
    "changed_files", "check_runs",
)


class _Config:
    def __init__(self, seconds=60):
        self.seconds = seconds

    def github_poll_seconds(self):
        return self.seconds


class _Unset:
    def github_poll_seconds(self):
        raise ConfigError("required config value 'github-poll-seconds' is not set")


def _github(**kw):
    base_keys = {pr: "acme/gadget@main" for pr in _B}
    return FakeGitHub(
        updated_ats={pr: 100.0 for pr in _ALL}, base_keys=base_keys,
        head_shas={pr: "h-" + pr[-8:] for pr in _ALL}, **kw)


class _Pool:
    def __init__(self, github=None, runner=None):
        self.github = github or _github()
        self.snapshot = PrSnapshot(self.github)
        self.runner = runner or InlineGithubPollRunner()
        self.status = FakeGithubBudgetStatus()
        self.fs = FakeFs()
        self.gate = GithubPollUseCase(
            self.snapshot, self.github, self.runner, _Config(), PrWrites(time.monotonic),
            self.status, lambda: 1000.0, self.fs)

    def log_lines(self):
        raw = self.fs._files.get("logs/run.log", b"")
        return raw.decode("utf-8").splitlines()

    def tick(self, now, prs=_ALL, files=(), checks=()):
        for pr in prs:
            self.snapshot.pr_sync_state(pr)
        for pr, sha in files:
            self.snapshot.changed_files(pr, sha)
        for pr, sha in checks:
            self.snapshot.check_runs(pr, sha)
        return self.gate.execute(now)

    def names(self):
        return [c[0] for c in self.github.calls]

    def reset(self):
        self.github.calls.clear()


class TestBudgetRead(unittest.TestCase):
    def test_a_cycle_publishes_limit_remaining_reset_and_read_time(self):
        pool = _Pool()
        pool.github.rate_limit_reading = RateLimit(5000, 4261, 1792503970)

        pool.tick(0)

        self.assertEqual(
            pool.status.load(),
            {"limit": 5000, "remaining": 4261, "reset": 1792503970, "read_at": 1000.0})

    def test_exactly_one_rate_limit_read_per_cycle_even_with_no_wanted_prs(self):
        pool = _Pool()
        pool.github.rate_limit_reading = RateLimit(5000, 4000, 1792503970)

        pool.tick(0, prs=[])
        pool.tick(60, prs=[])
        pool.tick(61, prs=[_A[0]])

        self.assertEqual(pool.names().count("rate_limit"), 3)
        self.assertEqual(len(pool.status.saves), 3)

    def test_a_failed_read_leaves_the_previous_file_unchanged(self):
        pool = _Pool()
        pool.github.rate_limit_reading = RateLimit(5000, 4000, 1792503970)
        pool.tick(0)
        before = pool.status.load()
        pool.github.rate_limit_reading = ReadFailure(1, "boom")

        pool.tick(60)

        self.assertEqual(pool.status.load(), before)
        self.assertEqual(len(pool.status.saves), 1)


class TestCallCounts(unittest.TestCase):
    def setUp(self):
        self.pool = _Pool()
        self.pool.tick(0)
        self.pool.reset()

    def test_nothing_moved_costs_three_calls_per_repo_and_none_per_pr(self):
        self.assertTrue(self.pool.tick(60))

        self.assertEqual(len(self.pool.github.calls), 7)
        self.assertEqual(sorted(self.pool.names()), sorted(
            ["list_prs", "repo_inline_comments", "branch_tip"] * 2 + ["rate_limit"]))
        self.assertFalse(set(self.pool.names()) & set(_PER_PR_CALLS))

    def test_one_push_costs_five_reads_and_one_compare(self):
        pr = _A[0]
        self.pool.github.touch(pr, 200.0)
        self.pool.github._head_shas[pr] = "h-new"

        self.pool.tick(60, files=[(pr, "h-new")])

        self.assertEqual(len(self.pool.github.calls), 13)
        self.assertEqual(self.pool.names().count("pr_view"), 1)
        self.assertEqual(self.pool.names().count("changed_files"), 1)
        self.assertEqual(self.pool.snapshot.head_sha(pr), "h-new")

    def test_one_merge_is_classified_by_the_listing_and_the_base_move_rereads_the_rest(self):
        pr = _A[0]
        self.pool.github._merged.add(pr)
        self.pool.github.touch(pr, 200.0)
        self.pool.github.advance_base("acme/widget", "main")

        self.pool.tick(60)

        self.assertEqual(len(self.pool.github.calls), 14)
        self.assertEqual(self.pool.names().count("pr_view"), 7)
        self.assertNotIn(("pr_view", pr), self.pool.github.calls)
        self.assertTrue(self.pool.snapshot.is_merged(pr))

    def test_a_closed_unmerged_pr_is_classified_without_a_view(self):
        pr = _B[0]
        self.pool.github._closed.add(pr)
        self.pool.github.touch(pr, 200.0)

        self.pool.tick(60)

        self.assertNotIn(("pr_view", pr), self.pool.github.calls)
        self.assertTrue(self.pool.snapshot.is_closed_unmerged(pr))
        self.assertFalse(self.pool.snapshot.is_merged(pr))

    def test_an_unchanged_pr_older_than_the_cutoff_is_never_classified_closed(self):
        self.pool.github.touch(_A[0], 200.0)

        self.pool.tick(60)

        self.assertFalse(self.pool.snapshot.is_closed_unmerged(_A[1]))
        self.assertFalse(self.pool.snapshot.is_merged(_A[1]))

    def test_a_pr_landing_on_the_cutoff_second_is_read_once_and_not_again(self):
        pool = _Pool(_github())
        pool.github.touch(_A[0], 90.0)
        pool.tick(0)
        pool.reset()
        pool.github.touch(_A[0], 100.0)

        pool.tick(60)

        self.assertIn(("pr_view", _A[0]), pool.github.calls)
        self.assertEqual(pool.names().count("pr_view"), 1)
        pool.reset()

        pool.tick(120)

        self.assertNotIn("pr_view", pool.names())

    def test_a_base_move_alone_rereads_each_pr_on_that_base_and_surfaces_behind(self):
        self.pool.github._behind.add(_B[0])
        self.pool.github.advance_base("acme/gadget", "main")

        self.pool.tick(60)

        self.assertEqual(self.pool.names().count("pr_view"), 8)
        self.assertTrue(self.pool.snapshot.pr_sync_state(_B[0]).behind)
        self.assertFalse(self.pool.snapshot.pr_sync_state(_B[1]).behind)

    def test_an_inline_comment_marks_the_pr_moved_without_an_updated_at_change(self):
        pr = _A[2]
        comment = Comment(author="r", body="fix", is_top_level=False, id="9", created_at=150.0)
        self.pool.github._timed_comments.append((150.0, comment))
        self.pool.github.inline_comment_on(pr, 150.0)

        self.pool.tick(60)

        self.assertIn(("pr_view", pr), self.pool.github.calls)
        self.assertEqual(self.pool.names().count("pr_view"), 1)
        self.assertEqual(self.pool.snapshot.pull_comments(pr, 0.0), [comment])

    def test_a_pending_ci_step_rereads_check_runs_every_poll_until_it_stops_asking(self):
        pr = _A[0]
        self.pool.tick(60, checks=[(pr, "h1")])
        self.assertEqual(self.pool.names().count("check_runs"), 1)
        self.assertEqual(self.pool.github.calls.count(("pr_view", pr)), 1)
        self.pool.reset()

        self.pool.tick(120, checks=[(pr, "h1")])
        self.assertEqual(self.pool.names().count("check_runs"), 1)
        self.assertEqual(self.pool.github.calls.count(("pr_view", pr)), 1)
        self.pool.reset()

        self.pool.tick(180)
        self.assertNotIn("check_runs", self.pool.names())


def _kwargs():
    return dict(
        updated_ats={pr: 100.0 for pr in _ALL},
        base_keys={pr: "acme/gadget@main" for pr in _B},
        head_shas={pr: "h-" + pr[-8:] for pr in _ALL},
        check_runs_by_sha=_failing_runs(),
    )


class _MovingHead(FakeGitHub):
    def __init__(self, moved_to, **kw):
        super().__init__(**kw)
        self._moved_to = moved_to
        self._checked = False

    def check_runs(self, pr, sha):
        self._checked = True
        return super().check_runs(pr, sha)

    def pr_view(self, pr):
        if self._checked and pr in self._moved_to:
            self._head_shas[pr] = self._moved_to[pr]
        return super().pr_view(pr)


def _failing_runs():
    return {
        (pr, "h-" + pr[-8:]): (CheckRun(name="build", status="completed", conclusion="failure"),)
        for pr in _ALL
    }


def _pool_after_first_poll(github):
    pool = _Pool(github=github)
    pool.tick(60)
    pool.reset()
    return pool


class TestChecksPublishedOnlyForAConfirmedHead(unittest.TestCase):
    def test_a_confirmed_head_publishes_its_checks(self):
        pool = _pool_after_first_poll(_github(check_runs_by_sha=_failing_runs()))
        pr = _A[0]
        sha = pool.snapshot.head_sha(pr)

        pool.tick(120, checks=[(pr, sha)])

        self.assertEqual(pool.names().count("check_runs"), 1)
        self.assertEqual(len(pool.snapshot.check_runs(pr, sha)), 1)

    def test_a_head_that_moved_during_the_poll_discards_the_checks_and_keeps_the_new_view(self):
        pr = _A[0]
        pool = _pool_after_first_poll(_MovingHead({pr: "moved"}, **_kwargs()))
        old = pool.snapshot.head_sha(pr)

        pool.tick(120, checks=[(pr, old)])

        self.assertIsInstance(pool.snapshot.check_runs(pr, old), NotYetRead)
        self.assertEqual(pool.snapshot.head_sha(pr), "moved")
        self.assertEqual(pool.snapshot.entry_of(pr).updated_at, 100.0)

    def test_a_failed_confirming_view_publishes_nothing(self):
        github = _github(check_runs_by_sha=_failing_runs())
        pool = _pool_after_first_poll(github)
        pr = _A[0]
        sha = pool.snapshot.head_sha(pr)
        github._failing_calls.add("pr_view")

        pool.tick(120, checks=[(pr, sha)])

        self.assertIsInstance(pool.snapshot.check_runs(pr, sha), NotYetRead)

    def test_only_the_confirmed_pr_of_two_publishes(self):
        first, second = _A[0], _A[1]
        pool = _pool_after_first_poll(_MovingHead({second: "moved"}, **_kwargs()))
        first_sha = pool.snapshot.head_sha(first)
        second_sha = pool.snapshot.head_sha(second)

        pool.tick(120, checks=[(first, first_sha), (second, second_sha)])

        self.assertEqual(len(pool.snapshot.check_runs(first, first_sha)), 1)
        self.assertIsInstance(pool.snapshot.check_runs(second, second_sha), NotYetRead)


class TestRequiredChecksPublished(unittest.TestCase):
    def _published(self, github):
        pool = _pool_after_first_poll(github)
        pr = _A[0]
        sha = pool.snapshot.head_sha(pr)
        return pool, pr, sha

    def test_poll_publishes_the_required_set_once_per_ttl(self):
        github = _github(check_runs_by_sha=_failing_runs(), required_by_base={"acme/widget@main": ["build"]})
        pool, pr, sha = self._published(github)

        pool.tick(120, checks=[(pr, sha)])
        pool.tick(121, checks=[(pr, sha)])

        self.assertEqual(pool.snapshot.required_checks("acme/widget@main"), frozenset({"build"}))
        self.assertEqual(pool.names().count("required_checks"), 1)

    def test_a_failed_read_publishes_nothing_and_is_retried(self):
        github = _github(check_runs_by_sha=_failing_runs(), failing_calls={"required_checks"})
        pool, pr, sha = self._published(github)

        pool.tick(120, checks=[(pr, sha)])
        pool.tick(300, checks=[(pr, sha)])

        self.assertIsInstance(pool.snapshot.required_checks("acme/widget@main"), NotYetRead)
        self.assertEqual(pool.names().count("required_checks"), 2)


class TestFailures(unittest.TestCase):
    def test_a_failed_read_keeps_the_old_entry_marks_it_stale_and_retries(self):
        pool = _Pool()
        pool.tick(0)
        pr = _A[0]
        pool.github.touch(pr, 200.0)
        pool.github._failing_calls.add("pr_view")

        pool.tick(60)

        self.assertTrue(pool.snapshot.is_stale(pr))
        self.assertEqual(pool.snapshot.head_sha(pr), "h-" + pr[-8:])
        pool.github._failing_calls.discard("pr_view")
        pool.reset()

        pool.tick(120)

        self.assertIn(("pr_view", pr), pool.github.calls)
        self.assertFalse(pool.snapshot.is_stale(pr))

    def test_the_cutoff_does_not_advance_past_a_failed_pr(self):
        pool = _Pool()
        pool.tick(0)
        pr = _A[0]
        pool.github.touch(pr, 200.0)
        pool.github._failing_calls.add("pr_view")
        pool.tick(60)
        pool.reset()

        pool.tick(120)

        self.assertIn(("list_prs", "acme/widget", 100.0), pool.github.calls)

    def test_a_failed_listing_marks_the_repos_prs_stale(self):
        pool = _Pool()
        pool.tick(0)
        pool.github._failing_calls.add("list_prs")

        pool.tick(60)

        self.assertTrue(all(pool.snapshot.is_stale(pr) for pr in _ALL))


class TestColdStart(unittest.TestCase):
    def test_the_first_poll_reads_each_pr_in_full_with_no_listing(self):
        pool = _Pool()

        pool.tick(0)

        names = pool.names()
        self.assertNotIn("list_prs", names)
        self.assertNotIn("repo_inline_comments", names)
        self.assertEqual(names.count("pr_view"), 16)
        self.assertEqual(pool.snapshot.head_sha(_A[0]), "h-" + _A[0][-8:])
        pool.reset()

        pool.tick(60)

        self.assertEqual(pool.names().count("list_prs"), 2)

    def test_no_gated_prs_runs_a_budget_only_cycle_and_a_later_pr_starts_a_poll_at_once(self):
        pool = _Pool()

        self.assertTrue(pool.tick(0, prs=[]))
        self.assertEqual(pool.names(), ["rate_limit"])
        self.assertEqual(pool.runner.starts, 1)
        self.assertTrue(pool.tick(5, prs=[_A[0]]))
        self.assertEqual(pool.runner.starts, 2)

    def test_a_budget_only_cycle_is_not_repeated_before_the_poll_is_due(self):
        pool = _Pool()
        pool.tick(0, prs=[])

        self.assertFalse(pool.tick(5, prs=[]))
        self.assertEqual(pool.runner.starts, 1)

    def test_the_poll_does_not_restart_before_it_is_due(self):
        pool = _Pool()
        pool.tick(0)

        self.assertFalse(pool.tick(59))
        self.assertTrue(pool.tick(60))


class TestStateDisagreement(unittest.TestCase):
    def _stuck(self):
        pool = _Pool()
        pool.tick(0)
        pool.github.touch(_A[0], 200.0)
        pool.tick(60)
        self.assertEqual(pool.snapshot.entry_of(_A[0]).state, "OPEN")
        return pool

    def test_a_merge_after_the_entry_took_the_final_updated_at_is_registered_next_poll(self):
        pool = self._stuck()
        pool.github._merged.add(_A[0])
        pool.reset()

        pool.tick(120)

        self.assertTrue(pool.snapshot.is_merged(_A[0]))
        self.assertNotIn(("pr_view", _A[0]), pool.github.calls)

    def test_a_close_after_the_entry_took_the_final_updated_at_is_registered_next_poll(self):
        pool = self._stuck()
        pool.github._closed.add(_A[0])

        pool.tick(120)

        self.assertTrue(pool.snapshot.is_closed_unmerged(_A[0]))
        self.assertFalse(pool.snapshot.is_merged(_A[0]))

    def test_the_poll_after_a_classified_merge_is_quiet_again(self):
        pool = self._stuck()
        pool.github._merged.add(_A[0])
        pool.tick(120)
        pool.reset()

        pool.tick(180)

        self.assertEqual(len(pool.github.calls), 7)
        self.assertFalse(set(pool.names()) & set(_PER_PR_CALLS))

    def test_a_reopened_pr_is_read_once_then_quiet(self):
        pool = _Pool(github=_github(closed_prs=[_A[0]]))
        pool.tick(0)
        pool.tick(60)
        pool.github._closed.discard(_A[0])
        pool.reset()

        pool.tick(120)
        self.assertEqual(pool.names().count("pr_view"), 1)
        pool.reset()
        pool.tick(180)

        self.assertEqual(pool.names().count("pr_view"), 0)


class TestRunLogFailures(unittest.TestCase):
    def test_a_failed_listing_writes_one_line_per_repo(self):
        pool = _Pool()
        pool.tick(0)
        pool.github._failing_calls.add("list_prs")

        pool.tick(60)

        lines = pool.log_lines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("github" in line and "list_prs" in line for line in lines))
        self.assertTrue(any("acme/widget" in line for line in lines))
        self.assertTrue(any("acme/gadget" in line and "(exit 1): boom" in line for line in lines))

    def test_a_failed_listing_and_inline_read_write_two_lines_per_repo(self):
        pool = _Pool()
        pool.tick(0)
        pool.github._failing_calls.update(["list_prs", "repo_inline_comments"])

        pool.tick(60)

        self.assertEqual(len(pool.log_lines()), 4)

    def test_a_failed_cold_start_view_writes_one_line_per_pr(self):
        pool = _Pool(github=_github(failing_calls=["pr_view"]))

        pool.tick(0)

        lines = pool.log_lines()
        self.assertEqual(pool.names().count("pr_view"), 16)
        self.assertEqual(len(lines), 16)
        for pr in _ALL:
            self.assertEqual(sum(pr in line for line in lines), 1)

    def test_only_the_prs_that_failed_are_logged_and_they_are_reread(self):
        pool = _Pool(github=_github(failing_prs=[_A[0], _A[1]]))
        pool.tick(0)

        lines = pool.log_lines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(any(_A[0] in line for line in lines))
        self.assertTrue(any(_A[1] in line for line in lines))
        self.assertTrue(pool.snapshot.is_stale(_A[0]))
        self.assertFalse(pool.snapshot.is_stale(_A[2]))
        pool.github._failing_prs.clear()
        pool.reset()

        pool.tick(60)

        self.assertEqual(pool.names().count("pr_view"), 2)
        self.assertFalse(pool.snapshot.is_stale(_A[0]))

    def test_a_quiet_poll_writes_nothing(self):
        pool = _Pool()
        pool.tick(0)
        pool.tick(60)

        self.assertEqual(pool.log_lines(), [])

    def test_a_failed_compare_and_check_read_write_one_line_each(self):
        pool = _Pool()
        pool.tick(0)
        pool.github._failing_calls.update(["changed_files", "check_runs"])

        pool.tick(60, files=[(_A[0], "h-new")], checks=[(_A[1], "h-" + _A[1][-8:])])

        lines = pool.log_lines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(any("changed_files" in line and _A[0] in line for line in lines))
        self.assertTrue(any("check_runs" in line and _A[1] in line for line in lines))

    def test_a_failed_tip_read_is_logged(self):
        pool = _Pool()
        pool.tick(0)
        pool.github._failing_calls.add("branch_tip")

        pool.tick(60)

        lines = pool.log_lines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("branch_tip" in line for line in lines))


class TestRunnerAndConfig(unittest.TestCase):
    def test_a_poll_still_running_is_not_restarted(self):
        pool = _Pool(runner=BlockingGithubPollRunner())

        self.assertTrue(pool.tick(0))
        self.assertFalse(pool.tick(60))
        self.assertFalse(pool.tick(600))
        self.assertEqual(pool.runner.starts, 1)
        self.assertEqual(pool.github.calls, [])

    def test_an_unset_key_fails_at_construction_naming_it(self):
        github = _github()
        with self.assertRaises(ConfigError) as ctx:
            GithubPollUseCase(PrSnapshot(github), github, InlineGithubPollRunner(), _Unset(), PrWrites(time.monotonic), FakeGithubBudgetStatus(), time.time, FakeFs())

        self.assertIn("github-poll-seconds", str(ctx.exception))

    def test_a_live_edit_of_the_interval_takes_effect(self):
        config = _Config(60)
        github = _github()
        snapshot = PrSnapshot(github)
        gate = GithubPollUseCase(snapshot, github, InlineGithubPollRunner(), config, PrWrites(time.monotonic), FakeGithubBudgetStatus(), time.time, FakeFs())
        snapshot.pr_sync_state(_A[0])
        gate.execute(0)
        config.seconds = 10
        snapshot.pr_sync_state(_A[0])

        self.assertTrue(gate.execute(10))

    def test_before_the_first_poll_finishes_readers_see_not_yet_read(self):
        pool = _Pool(runner=BlockingGithubPollRunner())
        pool.tick(0)

        self.assertIsInstance(pool.snapshot.pr_sync_state(_A[0]), NotYetRead)


if __name__ == "__main__":
    unittest.main()
