import unittest

from lightcycle.application.workflows.simulate import _phase_mismatch


class TestPhaseMismatch(unittest.TestCase):
    def test_matching_non_none_phases_produce_no_violation(self):
        self.assertEqual(
            _phase_mismatch(0, "pr_feedback", "gate", "target", "code", "code"), []
        )

    def test_differing_phases_produce_exactly_one_violation_naming_the_details(self):
        violations = _phase_mismatch(
            2, "pr_feedback", "spec-await-merge", "handle-feedback", "spec", "code"
        )
        self.assertEqual(len(violations), 1)
        msg = violations[0]
        self.assertIn("walk 2", msg)
        self.assertIn("pr_feedback", msg)
        self.assertIn("'spec-await-merge'", msg)
        self.assertIn("'handle-feedback'", msg)
        self.assertIn("'code'", msg)
        self.assertIn("'spec'", msg)

    def test_either_side_none_produces_no_violation(self):
        self.assertEqual(
            _phase_mismatch(0, "ci_failed_cap", "gate", "target", None, "code"), []
        )
        self.assertEqual(
            _phase_mismatch(0, "ci_failed_cap", "gate", "target", "code", None), []
        )
        self.assertEqual(
            _phase_mismatch(0, "ci_failed_cap", "gate", "target", None, None), []
        )


if __name__ == "__main__":
    unittest.main()
