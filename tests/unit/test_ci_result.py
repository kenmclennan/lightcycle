import unittest

from lightcycle.domain.pool import ci_outcome, failing_check, judged_checks, timed_out_check
from lightcycle.ports.github import CheckRun


def _run(name="build", status="completed", conclusion="success", started_at=0.0):
    return CheckRun(name=name, status=status, conclusion=conclusion, started_at=started_at)


def _running(name, started_at):
    return _run(name=name, status="in_progress", conclusion=None, started_at=started_at)


class TestCiOutcome(unittest.TestCase):
    def test_all_completed_success_is_success(self):
        checks = (_run(conclusion="success"), _run(name="test", conclusion="success"))
        self.assertEqual(ci_outcome(checks), "success")

    def test_one_still_in_progress_is_pending(self):
        checks = (_run(conclusion="success"), _run(name="test", status="in_progress", conclusion=None))
        self.assertEqual(ci_outcome(checks), "pending")

    def test_one_failure_among_passing_is_failure(self):
        checks = (_run(conclusion="success"), _run(name="test", conclusion="failure"))
        self.assertEqual(ci_outcome(checks), "failure")

    def test_cancelled_conclusion_is_failure(self):
        checks = (_run(conclusion="cancelled"),)
        self.assertEqual(ci_outcome(checks), "failure")

    def test_skipped_and_neutral_are_not_failing(self):
        checks = (
            _run(conclusion="success"),
            _run(name="lint", conclusion="skipped"),
            _run(name="docs", conclusion="neutral"),
        )
        self.assertEqual(ci_outcome(checks), "success")


class TestFailingCheck(unittest.TestCase):
    def test_names_the_first_failing_check(self):
        checks = (_run(conclusion="success"), _run(name="test", conclusion="failure"))
        self.assertEqual(failing_check(checks).name, "test")

    def test_none_when_nothing_is_failing(self):
        checks = (_run(conclusion="success"), _run(name="lint", conclusion="skipped"))
        self.assertIsNone(failing_check(checks))


_REQUIRED = frozenset({"build", "test"})


def _outcome(checks, required=_REQUIRED):
    return ci_outcome(checks, required, 10000.0, 3600)


class TestRequiredAndCeiling(unittest.TestCase):
    def test_non_required_check_in_progress_is_not_judged(self):
        checks = (_run("build"), _run("test"), _running("codacy", 1000.0))
        self.assertEqual(_outcome(checks), "success")

    def test_required_check_in_progress_under_ceiling_is_pending(self):
        checks = (_running("build", 9000.0), _run("test"), _run("codacy"))
        self.assertEqual(_outcome(checks), "pending")

    def test_required_check_exactly_at_ceiling_is_pending(self):
        self.assertEqual(_outcome((_running("build", 6400.0),)), "pending")

    def test_required_check_over_ceiling_is_timeout(self):
        checks = (_running("build", 6399.0),)
        self.assertEqual(_outcome(checks), "timeout")
        self.assertEqual(timed_out_check(checks, 10000.0, 3600).name, "build")

    def test_no_required_set_judges_all_so_a_hung_check_times_out(self):
        self.assertEqual(_outcome((_running("codacy", 1000.0),), required=None), "timeout")

    def test_nothing_matching_the_set_is_pending_on_the_absent_checks(self):
        self.assertEqual(_outcome((_run("codacy"),), required=frozenset({"build"})), "pending")

    def test_one_of_two_required_reported_is_pending(self):
        self.assertEqual(ci_outcome((_run("a"),), frozenset({"a", "b"}), 10000.0, 3600, 10000.0), "pending")

    def test_both_required_reported_green_is_success(self):
        self.assertEqual(ci_outcome((_run("a"), _run("b")), frozenset({"a", "b"}), 10000.0, 3600, 10000.0), "success")

    def test_absent_required_past_the_ceiling_is_timeout_naming_it(self):
        checks = (_run("b"),)
        required = frozenset({"a", "b"})
        self.assertEqual(ci_outcome(checks, required, 10000.0, 3600, 6399.0), "timeout")
        self.assertEqual(timed_out_check(judged_checks(checks, required, 6399.0), 10000.0, 3600).name, "a")

    def test_required_failure_with_others_in_progress_is_failure(self):
        checks = (_run("build", conclusion="failure"), _run("test"), _running("codacy", 9900.0))
        self.assertEqual(_outcome(checks), "failure")

    def test_running_required_check_defers_a_failure(self):
        checks = (_run("build", conclusion="failure"), _running("test", 9900.0))
        self.assertEqual(_outcome(checks), "pending")

    def test_failing_non_required_check_is_not_judged(self):
        checks = (_run("build"), _run("test"), _run("codacy", conclusion="failure"))
        self.assertEqual(_outcome(checks), "success")

    def test_unknown_start_never_times_out(self):
        self.assertIsNone(timed_out_check((_running("build", 0.0),), 10000.0, 3600))

    def test_no_ceiling_disables_timeout(self):
        self.assertIsNone(timed_out_check((_running("build", 1.0),), 10000.0, None))

    def test_judged_checks_with_no_set_is_everything(self):
        checks = (_run("build"), _run("codacy"))
        self.assertEqual(judged_checks(checks, None), checks)


def _empty(elapsed, runs=0, expected=("ci.yml",), now=10000.0, since=None):
    since = now - elapsed if since is None else since
    return ci_outcome(
        (), None, now, 3600, since, runs=runs, expected=expected, start_window=600, quiet_wait=60)


class TestEmptyCheckSet(unittest.TestCase):
    def test_a_fresh_head_with_no_runs_read_is_pending_not_success(self):
        self.assertEqual(ci_outcome((), None, 10000.0, 3600, 9999.0), "pending")

    def test_unread_runs_are_pending_whatever_the_elapsed_time(self):
        self.assertEqual(_empty(700, runs=None), "pending")

    def test_unclassified_expectation_is_pending(self):
        self.assertEqual(_empty(5000, expected=None), "pending")

    def test_unknown_since_is_pending(self):
        self.assertEqual(_empty(0, since=0.0), "pending")

    def test_expected_workflow_inside_the_start_window_is_pending(self):
        self.assertEqual(_empty(1), "pending")

    def test_exactly_on_the_start_window_is_pending(self):
        self.assertEqual(_empty(600), "pending")

    def test_past_the_start_window_with_an_expected_workflow_is_stalled(self):
        self.assertEqual(_empty(601), "stalled")

    def test_no_expected_workflow_exactly_on_the_quiet_wait_is_pending(self):
        self.assertEqual(_empty(60, expected=()), "pending")

    def test_no_expected_workflow_past_the_quiet_wait_is_success(self):
        self.assertEqual(_empty(61, expected=()), "success")

    def test_a_listed_run_exactly_on_the_ceiling_is_pending(self):
        self.assertEqual(_empty(3600, runs=1), "pending")

    def test_a_listed_run_past_the_ceiling_is_timeout(self):
        self.assertEqual(_empty(3601, runs=1), "timeout")

    def test_a_listed_run_is_never_stalled_or_success(self):
        for elapsed in (1, 601, 3000):
            self.assertEqual(_empty(elapsed, runs=1), "pending")
            self.assertEqual(_empty(elapsed, runs=1, expected=()), "pending")


class TestEveryNonCompletedStatusTimesOut(unittest.TestCase):
    def test_queued_past_the_ceiling_from_started_at_is_timeout(self):
        checks = (_run("build", status="queued", conclusion=None, started_at=6399.0),)
        self.assertEqual(_outcome(checks), "timeout")
        self.assertEqual(timed_out_check(checks, 10000.0, 3600).name, "build")

    def test_queued_exactly_on_the_ceiling_is_pending(self):
        checks = (_run("build", status="queued", conclusion=None, started_at=6400.0),)
        self.assertEqual(_outcome(checks), "pending")

    def test_other_statuses_time_out_like_in_progress(self):
        for status in ("waiting", "pending", "requested"):
            checks = (_run("build", status=status, conclusion=None, started_at=6399.0),)
            self.assertEqual(_outcome(checks), "timeout", status)

    def test_unknown_start_times_out_from_since(self):
        checks = (_run("build", status="queued", conclusion=None),)
        self.assertEqual(ci_outcome(checks, None, 10000.0, 3600, 6399.0), "timeout")
        self.assertEqual(ci_outcome(checks, None, 10000.0, 3600, 6400.0), "pending")
        self.assertEqual(ci_outcome(checks, None, 10000.0, 3600, 0.0), "pending")

    def test_a_completed_check_never_times_out(self):
        self.assertIsNone(timed_out_check((_run("build", started_at=1.0),), 10000.0, 3600))
