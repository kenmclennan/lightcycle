import pathlib
import unittest
from types import SimpleNamespace

from lightcycle.domain.flow.flow import Flow, outcome_counts, pr_conflict_failures
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.flow.hooks import CAP_SPECS, CONSECUTIVE, FAILURES, TOTAL, Cap
from lightcycle.domain.flow.step_def import StepDef

_LIBRARY = pathlib.Path(__file__).resolve().parents[1] / "support" / "library"


class TestStepDef(unittest.TestCase):
    def test_defaults_are_empty(self):
        sd = StepDef()
        self.assertIsNone(sd.owner)
        self.assertEqual(sd.routes, {})
        self.assertEqual(sd.caps, {})
        self.assertEqual(sd.hooks, frozenset())
        self.assertIsNone(sd.primary)
        self.assertIsNone(sd.display)


_EVERY_HOOK_TEXT = """
entry: build

edges:
  build   done     review           primary
  review  merged   cleanup
  review  changes  build

hooks:
  pr_merge              review  merged
  pr_close              review  abandoned
  pr_feedback           review  handle-feedback
  pr_conflict           review  conflicted
  pr_conflict_cap       review  3
  pr_conflict_escalate  review  gave-up
  mention_token         review  @lc
  review_bot_allowlist  review  bot-a  bot-b
  ci_failed_cap         review  ci-failed  3  review-ci
  review_rounds_cap     review  rejected  review-rounds-exceeded
  deploy_green          review  true

workspace:
  review  specs

phase:
  review  code

display:
  review  Review the PR
"""


class TestStepDefFromGraph(unittest.TestCase):
    def setUp(self):
        self.graph = parse_graph(_EVERY_HOOK_TEXT)

    def test_every_declared_hook_is_carried_onto_the_step_def(self):
        sd = StepDef.from_graph(self.graph, "review")
        self.assertEqual(sd.routes, {"merged": "cleanup", "changes": "build"})
        self.assertEqual(sd.pr_merge, "merged")
        self.assertEqual(sd.pr_close, "abandoned")
        self.assertEqual(sd.pr_feedback, "handle-feedback")
        self.assertEqual(sd.pr_conflict, "conflicted")
        self.assertEqual(sd.mention_token, "@lc")
        self.assertFalse(hasattr(sd, "review_bot_allowlist"))
        self.assertEqual(
            dict(sd.caps),
            {
                "ci_failed_cap": Cap(
                    "ci_failed_cap", "ci-failed", CONSECUTIVE, limit=3,
                    escalate_stage="review-ci", retry=True,
                ),
                "pr_conflict_cap": Cap(
                    "pr_conflict_cap", "conflicted", FAILURES, limit=3,
                    escalate_outcome="gave-up", trigger_hook="pr_conflict",
                ),
                "pr_conflict_total_cap": Cap(
                    "pr_conflict_total_cap", "conflicted", TOTAL, limit=9,
                    escalate_outcome="gave-up", trigger_hook="pr_conflict",
                ),
                "review_rounds_cap": Cap(
                    "review_rounds_cap", "rejected", CONSECUTIVE,
                    limit_key="review-rounds-cap", escalate_stage="review-rounds-exceeded",
                ),
            },
        )
        self.assertEqual(sd.workspace, "specs")
        self.assertEqual(sd.phase, "code")
        self.assertEqual(
            sd.hooks,
            frozenset({
                "on_pr_merge", "on_pr_close", "on_pr_feedback", "on_pr_conflict",
                "on_pr_conflict_cap", "on_pr_conflict_escalate", "on_mention_token",
                "on_review_bot_allowlist", "on_ci_failed_cap", "on_review_rounds_cap",
                "on_deploy_green",
            }),
        )
        self.assertEqual(sd.display, "Review the PR")

    def test_a_stage_with_no_declared_primary_edge_has_no_primary(self):
        self.assertIsNone(StepDef.from_graph(self.graph, "review").primary)

    def test_a_stage_marked_primary_carries_it(self):
        self.assertEqual(StepDef.from_graph(self.graph, "build").primary, "done")

    def test_a_stage_with_no_hooks_returns_the_field_defaults(self):
        sd = StepDef.from_graph(self.graph, "build")
        self.assertEqual(sd.routes, {"done": "review"})
        self.assertIsNone(sd.pr_merge)
        self.assertIsNone(sd.pr_close)
        self.assertIsNone(sd.pr_feedback)
        self.assertIsNone(sd.pr_conflict)
        self.assertIsNone(sd.mention_token)
        self.assertEqual(sd.caps, {})
        self.assertIsNone(sd.workspace)
        self.assertIsNone(sd.phase)
        self.assertEqual(sd.hooks, frozenset())
        self.assertIsNone(sd.display)


class TestMalformedCaps(unittest.TestCase):
    def test_under_arity_occurrences_yield_no_cap(self):
        under = {
            "ci_failed_cap": ("review", "review  ci-failed", "review  ci-failed  3"),
            "review_rounds_cap": ("review", "review  rejected"),
            "pr_conflict_cap": ("review",),
            "pr_conflict_total_cap": ("review",),
        }
        for hook, occurrences in under.items():
            for occurrence in occurrences:
                with self.subTest(hook=hook, occurrence=occurrence):
                    graph = parse_graph("entry: build\n\nhooks:\n  %s  %s\n" % (hook, occurrence))
                    self.assertEqual(StepDef.from_graph(graph, "review").caps, {})

    def test_every_registered_cap_hook_is_covered_by_the_malformed_cases(self):
        self.assertEqual(
            sorted(spec.hook for spec in CAP_SPECS),
            ["ci_failed_cap", "pr_conflict_cap", "pr_conflict_total_cap", "review_rounds_cap"],
        )


class TestCapsParseOneRecordPerHook(unittest.TestCase):
    def test_a_step_declaring_two_caps_carries_both_independently(self):
        graph = parse_graph(
            "entry: build\n\nhooks:\n"
            "  ci_failed_cap  review  ci-failed  3  review-ci\n"
            "  review_rounds_cap  review  rejected  too-many\n"
        )
        sd = StepDef.from_graph(graph, "review")
        self.assertEqual(list(sd.caps), ["ci_failed_cap", "review_rounds_cap"])
        self.assertEqual(sd.caps["ci_failed_cap"].escalate_stage, "review-ci")
        self.assertEqual(sd.caps["review_rounds_cap"].escalate_stage, "too-many")

    def test_a_cap_belongs_only_to_the_stage_that_declares_it(self):
        graph = parse_graph(
            "entry: build\n\nhooks:\n  ci_failed_cap  review  ci-failed  3  review-ci\n"
        )
        self.assertEqual(StepDef.from_graph(graph, "build").caps, {})


class TestFlowStepDef(unittest.TestCase):
    def test_returns_the_stored_step_def(self):
        sd = StepDef(phase="spec")
        flow = Flow({"s": sd})
        self.assertIs(flow.step_def("s"), sd)

    def test_returns_a_null_step_def_for_an_absent_stage(self):
        self.assertEqual(Flow({}).step_def("missing"), StepDef())
        self.assertEqual(Flow({"s": StepDef()}).step_def("other"), StepDef())


class TestPhase(unittest.TestCase):
    def test_flow_phase_of_returns_the_declared_phase(self):
        flow = Flow({"s": StepDef(phase="spec"), "c": StepDef(phase="code")})
        self.assertEqual(flow.step_def("s").phase, "spec")
        self.assertEqual(flow.step_def("c").phase, "code")

    def test_flow_phase_of_is_none_when_undeclared(self):
        self.assertIsNone(Flow({"s": StepDef()}).step_def("s").phase)
        self.assertIsNone(Flow({}).step_def("missing").phase)


class TestDisplay(unittest.TestCase):
    def test_flow_display_of_returns_the_declared_phrase(self):
        flow = Flow({"s": StepDef(display="Writing the spec"), "c": StepDef(display="Coding")})
        self.assertEqual(flow.step_def("s").display, "Writing the spec")
        self.assertEqual(flow.step_def("c").display, "Coding")

    def test_flow_display_of_is_none_when_undeclared(self):
        self.assertIsNone(Flow({"s": StepDef()}).step_def("s").display)
        self.assertIsNone(Flow({}).step_def("missing").display)


class TestConflictTransition(unittest.TestCase):
    def _flow(self, total=None):
        lines = [
            "edges:",
            "  resolve  conflicted  fix",
            "  resolve  give-up     stop",
            "hooks:",
            "  pr_conflict           resolve  conflicted",
            "  pr_conflict_cap       resolve  2",
            "  pr_conflict_escalate  resolve  give-up",
        ]
        if total is not None:
            lines.append("  pr_conflict_total_cap  resolve  %d" % total)
        graph = parse_graph("\n".join(lines) + "\n")
        return Flow({"resolve": StepDef.from_graph(graph, "resolve")})

    def _counts(self, failures, prior):
        return {TOTAL: prior, CONSECUTIVE: prior, FAILURES: failures}

    def _transition(self, flow, failures, prior):
        return flow.escalated_outcome("resolve", "conflicted", self._counts(failures, prior))

    def _fired(self, flow, failures, prior):
        cap = flow.fired_cap("resolve", "conflicted", self._counts(failures, prior))
        return None if cap is None else cap.hook

    def test_below_cap_passes_the_conflict_outcome(self):
        self.assertEqual(self._transition(self._flow(), 0, 0), "conflicted")
        self.assertEqual(self._transition(self._flow(), 1, 1), "conflicted")

    def test_failures_at_or_past_cap_escalate(self):
        self.assertEqual(self._transition(self._flow(), 2, 0), "give-up")
        self.assertEqual(self._transition(self._flow(), 3, 0), "give-up")

    def test_prior_conflicts_alone_below_total_cap_do_not_escalate(self):
        self.assertEqual(self._transition(self._flow(), 0, 5), "conflicted")

    def test_prior_conflicts_at_derived_total_cap_escalate(self):
        self.assertEqual(self._transition(self._flow(), 0, 6), "give-up")

    def test_declared_total_cap_overrides_the_derived_one(self):
        flow = self._flow(total=4)
        self.assertEqual(self._transition(flow, 0, 3), "conflicted")
        self.assertEqual(self._transition(flow, 0, 4), "give-up")

    def test_no_cap_passes_through(self):
        flow = Flow({"resolve": StepDef()})
        self.assertEqual(self._transition(flow, 9, 9), "conflicted")

    def test_no_escalate_outcome_never_escalates(self):
        cap = Cap("pr_conflict_cap", "conflicted", FAILURES, limit=1)
        flow = Flow({"resolve": StepDef(caps={"pr_conflict_cap": cap})})
        self.assertEqual(self._transition(flow, 9, 9), "conflicted")

    def test_failure_cap_is_named_when_both_trip(self):
        self.assertEqual(self._fired(self._flow(), 2, 6), "pr_conflict_cap")
        self.assertEqual(self._fired(self._flow(), 0, 6), "pr_conflict_total_cap")
        self.assertIsNone(self._fired(self._flow(), 1, 1))

    def test_total_cap_is_three_times_the_failure_cap_unless_declared(self):
        self.assertEqual(self._flow().step_def("resolve").caps["pr_conflict_total_cap"].limit, 6)
        self.assertEqual(
            self._flow(total=5).step_def("resolve").caps["pr_conflict_total_cap"].limit, 5)
        self.assertNotIn("pr_conflict_total_cap", StepDef().caps)


class TestCommittedBundleTotalCap(unittest.TestCase):
    def test_spec_driven_declares_no_total_cap_and_derives_nine(self):
        graph = parse_graph((_LIBRARY / "workflows" / "spec-driven.md").read_text())
        stage = "code-await-merge"

        self.assertEqual(graph.hook_occurrences("pr_conflict_total_cap"), ())
        self.assertEqual(StepDef.from_graph(graph, stage).caps["pr_conflict_total_cap"].limit, 9)


class TestOutcomeCounts(unittest.TestCase):
    def test_counts_total_and_consecutive_and_carries_failures(self):
        history = [SimpleNamespace(outcome=o) for o in ("c", "x", "c", "c")]
        self.assertEqual(
            outcome_counts(history, "c", 5), {TOTAL: 3, CONSECUTIVE: 2, FAILURES: 5})


class TestPrConflictFailures(unittest.TestCase):
    def test_empty_history_has_no_failures(self):
        self.assertEqual(pr_conflict_failures([], "A", 0), 0)

    def test_one_prior_step_on_the_same_tip_is_one_failure(self):
        self.assertEqual(pr_conflict_failures(["A"], "A", 0), 1)

    def test_one_prior_step_on_a_moved_tip_is_clean(self):
        self.assertEqual(pr_conflict_failures(["A"], "B", 0), 0)

    def test_unknown_entries_never_count(self):
        self.assertEqual(pr_conflict_failures(["A", "A", None], "A", 0), 1)
        self.assertEqual(pr_conflict_failures([None, None], None, 0), 0)

    def test_unknown_current_tip_is_clean(self):
        self.assertEqual(pr_conflict_failures(["A", "A"], None, 0), 1)

    def test_escalated_resolutions_add_to_the_count(self):
        self.assertEqual(pr_conflict_failures(["A"], "A", 2), 3)

    def test_unmoved_then_moved_then_unmoved_base(self):
        self.assertEqual(pr_conflict_failures(["A", "A", "B", "B"], "B", 0), 3)


class TestRealBundleCaps(unittest.TestCase):
    def test_the_spec_driven_bundle_parses_to_the_caps_main_parses_today(self):
        text = (_LIBRARY / "workflows" / "spec-driven.md").read_text()
        graph = parse_graph(text)
        watch = StepDef.from_graph(graph, "watch-ci").caps["ci_failed_cap"]
        self.assertEqual((watch.outcome, watch.limit, watch.escalate_stage), ("ci-failed", 3, "review-ci"))
        conflict = StepDef.from_graph(graph, "code-await-merge").caps["pr_conflict_cap"]
        self.assertEqual(
            (conflict.outcome, conflict.limit, conflict.escalate_outcome),
            ("conflicted", 3, "gave-up"),
        )


if __name__ == "__main__":
    unittest.main()


class TestStaleBotAllowlistHook(unittest.TestCase):
    def test_a_declared_review_bot_allowlist_is_tolerated_and_unread(self):
        graph = parse_graph(_EVERY_HOOK_TEXT)
        sd = StepDef.from_graph(graph, "review")
        self.assertEqual(sd.mention_token, "@lc")
        self.assertEqual(sd.pr_merge, "merged")
        self.assertFalse(hasattr(sd, "review_bot_allowlist"))
