import unittest

from lightcycle.domain.pool import ci_outcome, failing_check
from lightcycle.ports.github import CheckRun


def _run(name="build", status="completed", conclusion="success"):
    return CheckRun(name=name, status=status, conclusion=conclusion)


class TestCiOutcome(unittest.TestCase):
    def test_no_checks_is_success(self):
        self.assertEqual(ci_outcome(()), "success")

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


if __name__ == "__main__":
    unittest.main()
