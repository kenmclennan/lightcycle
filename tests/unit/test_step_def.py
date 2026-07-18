import unittest

from lightcycle.domain.flow.flow import Flow
from lightcycle.domain.flow.step_def import CiCap, StepDef


class TestStepDef(unittest.TestCase):
    def test_defaults_are_empty(self):
        sd = StepDef()
        self.assertIsNone(sd.owner)
        self.assertEqual(sd.routes, {})
        self.assertIsNone(sd.ci_cap)
        self.assertEqual(sd.hooks, frozenset())

    def test_ci_cap_holds_outcome_n_target(self):
        cap = CiCap("ci-failed", 3, "review-ci")
        self.assertEqual((cap.outcome, cap.n, cap.target), ("ci-failed", 3, "review-ci"))


class TestPhase(unittest.TestCase):
    def test_flow_phase_of_returns_the_declared_phase(self):
        flow = Flow({"s": StepDef(phase="spec"), "c": StepDef(phase="code")})
        self.assertEqual(flow.phase_of("s"), "spec")
        self.assertEqual(flow.phase_of("c"), "code")

    def test_flow_phase_of_is_none_when_undeclared(self):
        self.assertIsNone(Flow({"s": StepDef()}).phase_of("s"))
        self.assertIsNone(Flow({}).phase_of("missing"))


class TestConflictTransition(unittest.TestCase):
    def _flow(self):
        return Flow({
            "resolve": StepDef(
                pr_conflict="conflicted", pr_conflict_cap=2, pr_conflict_escalate="give-up"
            )
        })

    def test_below_cap_passes_the_conflict_outcome(self):
        self.assertEqual(self._flow().pr_conflict_transition("resolve", "conflicted", 0), "conflicted")
        self.assertEqual(self._flow().pr_conflict_transition("resolve", "conflicted", 1), "conflicted")

    def test_at_or_past_cap_escalates(self):
        self.assertEqual(self._flow().pr_conflict_transition("resolve", "conflicted", 2), "give-up")

    def test_no_cap_passes_through(self):
        flow = Flow({"resolve": StepDef()})
        self.assertEqual(flow.pr_conflict_transition("resolve", "conflicted", 9), "conflicted")


if __name__ == "__main__":
    unittest.main()
