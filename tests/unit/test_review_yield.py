import dataclasses
import json
import unittest
from unittest import mock

from lightcycle.application.errors import UseCaseError
from lightcycle.application.feedback.review_yield import ReviewYieldUseCase
from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.flow.escapes import EscapeRecorder
from lightcycle.application.pool.dispatch_pr_feedback import DispatchPrFeedbackUseCase
from lightcycle.application.work.link_artifact import LinkArtifactInput, LinkArtifactUseCase
from lightcycle.application.work.link_source import LinkSourceUseCase
from lightcycle.domain.feedback.review_yield import (
    classify_source,
    parse_findings,
)
from lightcycle.domain.money import Cost
from lightcycle.ports.github import Comment
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_dispatch_pr_feedback import _FlowAdapter as _BaseFlowAdapter, plant_pr


class _FlowAdapter(_BaseFlowAdapter):
    def step_declared(self, stage, name=None):
        return self._flow.declared(stage)

_METAS = {
    "writer": {"model": "sonnet", "step": "write-code", "routes": {"done": "review-code"},
               "phase": "code"},
    "reviewer": {"model": "sonnet", "step": "review-code",
                 "routes": {"done": "await-merge", "rejected": "write-code"},
                 "phase": "code", "review": "done"},
    "gate": {"step": "await-merge", "phase": "code", "sends-back": "changes, conflicted",
             "routes": {"changes": "write-code", "merged": "cleanup", "conflicted": "write-code"},
             "on_pr_feedback": "handle-feedback", "on_mention_token": "@lc"},
    "handle-feedback": {"model": "sonnet", "step": "handle-feedback",
                        "routes": {"done": "await-merge"}, "phase": "code"},
}
_FLOW = flow_from_metas(_METAS)
_TRUST = dict(trusted_authors=lambda: frozenset({"ken"}), held_shortcode=lambda: "HLD")


class _Rig:
    def __init__(self):
        self.store = FakeStore()
        self.item = self.store.create_item("feature", "d")
        self.rid = plant_pr(self.store, self.item, "https://github.com/x/y/pull/1", phase="code")
        self.complete = CompleteStepUseCase(self.store, _FlowAdapter(_FLOW))
        self.current = self.store.create_step(stage="write-code", role="agent", item=self.item)

    def done(self, outcome, note=None):
        finished = self.current
        self.current = self.complete.execute(
            CompleteInput(step=finished, outcome=outcome, note=note)).next_step
        return finished

    def to_gate(self):
        self.done("done")
        return self.done("done")


class TestFlowParsing(unittest.TestCase):
    def test_review_and_sends_back_are_read_onto_the_step_def(self):
        self.assertEqual(_FLOW.step_def("review-code").review, "done")
        self.assertEqual(_FLOW.step_def("await-merge").sends_back, ("changes", "conflicted"))

    def test_absent_keys_give_none_and_empty(self):
        sd = _FLOW.step_def("write-code")
        self.assertIsNone(sd.review)
        self.assertEqual(sd.sends_back, ())

    def test_two_stages_bound_to_one_step_file_both_inherit(self):
        flow = flow_from_metas({
            "a": {"model": "sonnet", "step": "first", "routes": {"done": "second"},
                  "review": "done"},
        })
        self.assertEqual(flow.step_def("first").review, "done")


class TestClassifySource(unittest.TestCase):
    trusted = frozenset({"ken"})

    def test_no_authors_is_unknown(self):
        self.assertEqual(classify_source([], self.trusted), "unknown")

    def test_one_trusted_one_bot_one_other(self):
        self.assertEqual(classify_source(["ken"], self.trusted), "trusted")
        self.assertEqual(classify_source(["copilot[bot]"], self.trusted), "bot")
        self.assertEqual(classify_source(["stranger"], self.trusted), "other")

    def test_mixed_classes(self):
        self.assertEqual(classify_source(["ken", "copilot[bot]"], self.trusted), "mixed")

    def test_casing_is_folded(self):
        self.assertEqual(classify_source(["KEN"], self.trusted), "trusted")
        self.assertEqual(classify_source(["Copilot[BOT]"], self.trusted), "bot")


class TestParseFindings(unittest.TestCase):
    good = {"severity": "critical", "kind": "correctness", "file": "a.py", "line": 3,
            "summary": "one line"}

    def _refused(self, **change):
        element = dict(self.good, **change)
        with self.assertRaises(ValueError):
            parse_findings(json.dumps([element]))

    def test_a_valid_array_and_an_empty_array(self):
        self.assertEqual(parse_findings(json.dumps([self.good])), [self.good])
        self.assertEqual(parse_findings("[]"), [])

    def test_null_file_and_line_are_valid(self):
        parse_findings(json.dumps([dict(self.good, file=None, line=None)]))

    def test_each_rule_broken_once(self):
        self._refused(extra="x")
        self._refused(severity="")
        self._refused(kind=3)
        self._refused(summary="two\nlines")
        self._refused(file=None, line=3)
        self._refused(line="3")
        self._refused(line=0)
        self._refused(file=7)
        broken = dict(self.good)
        del broken["kind"]
        with self.assertRaises(ValueError):
            parse_findings(json.dumps([broken]))

    def test_not_an_array_or_not_json_is_refused(self):
        with self.assertRaises(ValueError):
            parse_findings("{}")
        with self.assertRaises(ValueError):
            parse_findings("nope")


class TestAttachFindings(unittest.TestCase):
    def setUp(self):
        self.rig = _Rig()
        self.uc = LinkArtifactUseCase(self.rig.store, _FlowAdapter(_FLOW))
        self.rig.done("done")
        self.review = self.rig.current
        self.good = json.dumps([{"severity": "low", "kind": "style", "file": None,
                                 "line": None, "summary": "nit"}])

    def _attach(self, step, value, replace=False):
        self.uc.execute(LinkArtifactInput(
            item=step, atype="review-findings", value=value, replace=replace))

    def test_stored_as_an_internal_artifact_of_the_step(self):
        self._attach(self.review, self.good)
        found = [a for a in self.rig.store.item_artifacts(self.review)
                 if a.type == "review-findings"]
        self.assertEqual([(a.value, a.internal) for a in found], [(self.good, True)])

    def test_a_non_review_step_is_refused(self):
        with self.assertRaises(UseCaseError):
            self._attach(self.rig.store.children(self.rig.item)[0].id, self.good)

    def test_an_invalid_shape_stores_nothing(self):
        with self.assertRaises(UseCaseError):
            self._attach(self.review, "[{}]")
        self.assertEqual(
            [a for a in self.rig.store.item_artifacts(self.review)
             if a.type == "review-findings"], [])

    def test_a_second_attach_needs_replace(self):
        self._attach(self.review, self.good)
        with self.assertRaises(UseCaseError):
            self._attach(self.review, "[]")
        self._attach(self.review, "[]", replace=True)
        values = [a.value for a in self.rig.store.item_artifacts(self.review)
                  if a.type == "review-findings"]
        self.assertEqual(values, ["[]"])

    def test_the_source_link_types_cannot_be_attached(self):
        for atype in ("caused-by", "found-by"):
            with self.assertRaises(UseCaseError):
                self.uc.execute(LinkArtifactInput(item=self.rig.item, atype=atype, value="x"))


class TestChangeRequestEscapes(unittest.TestCase):
    def setUp(self):
        self.rig = _Rig()

    def _rows(self):
        return self.rig.store.escapes_since("")

    def test_worked_example_records_one_escape_against_the_passing_verdict(self):
        self.rig.done("done")
        self.rig.done("rejected")
        self.rig.done("done")
        verdict = self.rig.done("done")
        gate = self.rig.current
        self.assertEqual(self._rows(), [])
        self.rig.done("changes", note="rename the thing")
        (row,) = self._rows()
        self.assertEqual(
            (row.trigger_step, row.verdict_step, row.via, row.note, row.source, row.item),
            (gate, verdict, "change-request", "rename the thing", "unknown", self.rig.item))

    def test_changes_before_any_pass_records_nothing(self):
        gate = self.rig.store.create_step(stage="await-merge", role="human", item=self.rig.item)
        CompleteStepUseCase(self.rig.store, _FlowAdapter(_FLOW)).execute(
            CompleteInput(step=gate, outcome="changes", note="early"))
        self.assertEqual(self._rows(), [])

    def test_a_rejection_alone_is_not_a_pass(self):
        self.rig.done("done")
        self.rig.done("rejected")
        self.assertEqual(self._rows(), [])

    def test_a_second_pass_then_second_changes_names_the_later_verdict(self):
        self.rig.to_gate()
        self.rig.done("changes", note="one")
        self.rig.done("done")
        later = self.rig.done("done")
        self.rig.done("changes", note="two")
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].verdict_step, later)
        self.assertNotEqual(rows[0].verdict_step, later)

    def test_replaying_the_completion_adds_no_row(self):
        self.rig.to_gate()
        gate = self.rig.current
        self.rig.done("changes", note="one")
        CompleteStepUseCase(self.rig.store, _FlowAdapter(_FLOW)).execute(
            CompleteInput(step=gate, outcome="changes", note="one"))
        self.assertEqual(len(self._rows()), 1)

    def test_an_outcome_that_does_not_send_back_records_nothing_and_does_no_recorder_work(self):
        self.rig.to_gate()
        gate = self.rig.current
        with mock.patch.object(EscapeRecorder, "_record") as recorder:
            self.rig.complete.execute(CompleteInput(step=gate, outcome="merged"))
        recorder.assert_not_called()
        self.assertEqual(self._rows(), [])

    def test_a_stage_with_no_review_in_its_run_records_nothing(self):
        flow = flow_from_metas({
            "w": {"model": "sonnet", "step": "write-code", "routes": {"done": "await-merge"},
                  "phase": "code"},
            "g": {"step": "await-merge", "phase": "code", "sends-back": "changes",
                  "routes": {"changes": "write-code"}},
        })
        store = FakeStore()
        item = store.create_item("f", "d")
        plant_pr(store, item, "https://github.com/x/y/pull/9", phase="code")
        complete = CompleteStepUseCase(store, _FlowAdapter(flow))
        first = store.create_step(stage="write-code", role="agent", item=item)
        gate = complete.execute(CompleteInput(step=first, outcome="done")).next_step
        complete.execute(CompleteInput(step=gate, outcome="changes"))
        self.assertEqual(store.escapes_since(""), [])


class TestPrCommentEscapes(unittest.TestCase):
    def _dispatch(self, comments, author="ken"):
        rig = _Rig()
        gate = rig.to_gate()
        gate_step = rig.current
        gh = FakeGitHub(push_time=1000.0, timed_comments=comments)
        uc = DispatchPrFeedbackUseCase(
            rig.store, gh, _FlowAdapter(_FLOW), rig.complete, **_TRUST)
        uc.execute()
        return rig, gate, gate_step

    def _mention(self, ts, author="ken"):
        return (ts, Comment(author=author, body="@lc fix it", is_top_level=True,
                            id=str(ts), created_at=ts))

    def _inline(self, ts, author="ken"):
        return (ts, Comment(author=author, body="rename", is_top_level=False, path="a.py",
                            line=3, id=str(ts), created_at=ts))

    def test_a_mention_dispatched_to_rework_records_an_escape_from_a_trusted_author(self):
        rig, verdict_gate, gate_step = self._dispatch([self._mention(1500.0)])
        (row,) = rig.store.escapes_since("")
        feedback = [s for s in rig.store.children(rig.item) if s.stage == "handle-feedback"]
        self.assertEqual(len(feedback), 1)
        self.assertEqual((row.trigger_step, row.via, row.source, row.authors),
                         (feedback[0].id, "pr-comment", "trusted", "ken"))
        self.assertIn("1500.0", row.note)

    def test_an_inline_thread_dispatched_to_rework_records_an_escape(self):
        rig, _verdict, _gate = self._dispatch([self._inline(1500.0)])
        (row,) = rig.store.escapes_since("")
        self.assertEqual(row.source, "trusted")

    def test_an_approved_held_comment_records_an_escape_from_an_other_author(self):
        rig = _Rig()
        rig.to_gate()
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention(1500.0, "mallory")])
        uc = DispatchPrFeedbackUseCase(rig.store, gh, _FlowAdapter(_FLOW), rig.complete, **_TRUST)
        uc.execute()
        self.assertEqual(rig.store.escapes_since(""), [])
        held = rig.store.hold(rig.rid, "mention:1500.0")
        rig.store.decide_hold(held.step_id, "approved")
        uc.execute()
        (row,) = rig.store.escapes_since("")
        self.assertEqual((row.via, row.source, row.authors), ("pr-comment", "other", "mallory"))

    def test_no_row_when_the_review_has_not_passed(self):
        store = FakeStore()
        item = store.create_item("f", "d")
        plant_pr(store, item, "https://github.com/x/y/pull/2", phase="code")
        store.create_step(stage="await-merge", role="human", item=item)
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention(1500.0)])
        complete = CompleteStepUseCase(store, _FlowAdapter(_FLOW))
        DispatchPrFeedbackUseCase(store, gh, _FlowAdapter(_FLOW), complete, **_TRUST).execute()
        self.assertEqual(store.escapes_since(""), [])
        self.assertEqual(
            len([s for s in store.children(item) if s.stage == "handle-feedback"]), 1)

    def test_a_store_failure_after_create_step_leaves_no_step_artifact_or_row(self):
        rig = _Rig()
        rig.to_gate()
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention(1500.0)])
        uc = DispatchPrFeedbackUseCase(rig.store, gh, _FlowAdapter(_FLOW), rig.complete, **_TRUST)
        with mock.patch.object(rig.store, "record_escape", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                uc.execute()
        self.assertEqual(
            [s for s in rig.store.children(rig.item) if s.stage == "handle-feedback"], [])
        self.assertEqual(rig.store.escapes_since(""), [])


class TestLinkSources(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.source = self.store.create_item("source", "d")
        self.fix = self.store.create_item("fix", "d")
        self.step = self.store.create_step(stage="write-code", role="agent", item=self.source)
        self.uc = LinkSourceUseCase(self.store)

    def _caused(self, item):
        return [a.value for a in self.store.item_artifacts(item) if a.type == "caused-by"]

    def test_repeated_links_are_stored_internally(self):
        other = self.store.create_item("other", "d")
        self.uc.execute(self.fix, [self.source, other], "audit")
        self.assertEqual(self._caused(self.fix), [self.source, other])
        found = [a for a in self.store.item_artifacts(self.fix) if a.type == "found-by"]
        self.assertEqual([(a.value, a.internal) for a in found], [("audit", True)])

    def test_unknown_step_and_self_links_are_refused(self):
        with self.assertRaises(UseCaseError):
            self.uc.execute(self.fix, ["nope"], None)
        with self.assertRaises(UseCaseError) as step_err:
            self.uc.execute(self.fix, [self.step], None)
        self.assertIn(self.source, str(step_err.exception))
        with self.assertRaises(UseCaseError):
            self.uc.execute(self.fix, [self.fix], None)
        self.assertEqual(self._caused(self.fix), [])

    def test_found_by_with_whitespace_or_too_long_is_refused(self):
        with self.assertRaises(UseCaseError):
            self.uc.execute(self.fix, None, "user report")
        with self.assertRaises(UseCaseError):
            self.uc.execute(self.fix, None, "x" * 41)

    def test_set_replaces_the_whole_set_and_unset_clears(self):
        other = self.store.create_item("other", "d")
        self.uc.execute(self.fix, [self.source], None)
        self.uc.execute(self.fix, [other], None)
        self.assertEqual(self._caused(self.fix), [other])
        self.uc.execute(self.fix, None, "driver")
        self.assertEqual(self._caused(self.fix), [other])
        self.uc.execute(self.fix, None, None, ("caused-by", "found-by"))
        self.assertEqual(self._caused(self.fix), [])
        self.assertEqual(
            [a for a in self.store.item_artifacts(self.fix) if a.type == "found-by"], [])


class TestReviewYield(unittest.TestCase):
    def _setup(self):
        rig = _Rig()
        rig.done("done")
        rejected = rig.done("rejected")
        rig.done("done")
        passed = rig.done("done")
        return rig, rejected, passed

    def _report(self, rig, since=None):
        return ReviewYieldUseCase(rig.store, _FlowAdapter(_FLOW)).execute(since)

    def test_counts_verdicts_passes_rejections_and_cost(self):
        rig, rejected, passed = self._setup()
        report = self._report(rig)
        (stage,) = report["stages"]
        self.assertEqual((stage["stage"], stage["pass_outcome"]), ("review-code", "done"))
        self.assertEqual((stage["verdicts"], stage["passes"], stage["rejections"]), (2, 1, 1))
        self.assertEqual(stage["cost_usd"], sum(r["cost_usd"] for r in stage["verdict_rows"]))
        self.assertEqual(
            {k for k in stage["verdict_rows"][0]},
            {"step", "item", "pass", "phase", "outcome", "closed_at", "cost_usd", "findings"})

    def test_cost_is_summed_across_verdict_rows(self):
        rig, rejected, passed = self._setup()
        real = rig.store.nodes_closed_since

        def priced(since):
            return [
                dataclasses.replace(s, usage_cost_usd=Cost.from_usd(0.25))
                if s.stage == "review-code" else s
                for s in real(since)
            ]

        with mock.patch.object(rig.store, "nodes_closed_since", side_effect=priced):
            stage = self._report(rig)["stages"][0]
        self.assertEqual(stage["cost_usd"], 0.5)
        self.assertEqual(stage["cost_usd"], sum(r["cost_usd"] for r in stage["verdict_rows"]))

    def test_findings_are_counted_and_absent_ones_are_not(self):
        rig, rejected, passed = self._setup()
        findings = [{"severity": "high", "kind": "bug", "file": "a.py", "line": 1,
                     "summary": "s"}]
        rig.store.add_artifact(rejected, "review-findings", json.dumps(findings), internal=True)
        rig.store.add_artifact(passed, "review-findings", "[]", internal=True)
        stage = self._report(rig)["stages"][0]["findings"]
        self.assertEqual(stage, {"verdicts_with_findings": 1, "verdicts_reporting_none": 1,
                                 "count": 1})

    def test_a_change_request_escape_is_attributed_with_its_source(self):
        rig, rejected, passed = self._setup()
        rig.done("changes", note="please")
        stage = self._report(rig)["stages"][0]
        self.assertEqual(stage["escapes"], {"count": 1, "by_source": {"unknown": 1}})
        (row,) = stage["escape_rows"]
        self.assertEqual(
            (row["kind"], row["verdict_step"], row["via"], row["note"]),
            ("rework", passed, "change-request", "please"))

    def test_a_post_merge_link_is_attributed_to_the_latest_passing_verdict(self):
        rig, rejected, passed = self._setup()
        fix = rig.store.create_item("fix", "d")
        LinkSourceUseCase(rig.store).execute(fix, [rig.item], "runtime")
        report = self._report(rig)
        stage = report["stages"][0]
        (row,) = stage["escape_rows"]
        self.assertEqual(
            (row["kind"], row["item"], row["linked_item"], row["found_by"],
             row["verdict_step"]),
            ("post-merge", fix, rig.item, "runtime", passed))
        self.assertEqual(stage["escapes"]["by_source"], {"post-merge": 1})
        self.assertEqual(report["unattributed_escapes"], [])

    def test_a_link_to_an_unreviewed_item_is_unattributed_not_dropped(self):
        rig, _r, _p = self._setup()
        unreviewed = rig.store.create_item("never reviewed", "d")
        fix = rig.store.create_item("fix", "d")
        LinkSourceUseCase(rig.store).execute(fix, [unreviewed], None)
        report = self._report(rig)
        self.assertEqual(report["stages"][0]["escapes"]["count"], 0)
        (row,) = report["unattributed_escapes"]
        self.assertEqual((row["item"], row["linked_item"], row["found_by"]),
                         (fix, unreviewed, None))

    def test_steps_whose_stage_the_flow_does_not_declare_are_counted_not_dropped(self):
        rig, _r, _p = self._setup()
        report = ReviewYieldUseCase(rig.store, _FlowAdapter(flow_from_metas({
            "x": {"model": "sonnet", "step": "other", "routes": {"done": "more"}},
        }))).execute(None)
        self.assertEqual(report["stages"], [])
        self.assertEqual(report["undeclared_steps"], 4)

    def test_mixed_window_counts_declared_and_undeclared(self):
        rig, _r, _p = self._setup()
        odd = rig.store.create_step(stage="mystery", role="agent", item=rig.item)
        rig.store.complete_step_atomic(odd, "done", None, None)
        report = self._report(rig)
        self.assertEqual(report["stages"][0]["verdicts"], 2)
        self.assertEqual(report["undeclared_steps"], 1)

    def test_the_since_boundary_day_is_included_and_the_day_before_is_not(self):
        rig, rejected, passed = self._setup()
        for step_id, stamp in ((rejected, "2026-10-01T00:00:01+01:00"),
                               (passed, "2026-09-30T23:59:59+01:00")):
            rig.store._records[step_id]["closed_at"] = stamp
        others = [s.id for s in rig.store.children(rig.item)
                  if s.stage == "review-code" and s.id not in (rejected, passed)]
        for step_id in others:
            rig.store._records[step_id]["closed_at"] = "2026-09-01T00:00:00+01:00"
        report = self._report(rig, "2026-10-01")
        self.assertEqual([r["step"] for r in report["stages"][0]["verdict_rows"]], [rejected])

    def test_the_json_shape_has_every_binding_key(self):
        rig, _r, _p = self._setup()
        report = self._report(rig, "2026-01-01")
        self.assertEqual(
            set(report), {"since", "stages", "unattributed_escapes", "undeclared_steps"})
        self.assertEqual(
            set(report["stages"][0]),
            {"workflow", "stage", "pass_outcome", "verdicts", "passes", "rejections", "cost_usd",
             "findings", "escapes", "verdict_rows", "escape_rows"})
        self.assertEqual(
            set(report["stages"][0]["findings"]),
            {"verdicts_with_findings", "verdicts_reporting_none", "count"})
        self.assertEqual(set(report["stages"][0]["escapes"]), {"count", "by_source"})
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
