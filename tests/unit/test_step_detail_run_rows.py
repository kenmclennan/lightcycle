import unittest

from lightcycle.application.work.step_detail import StepDetail
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.step_def import StepDef
from lightcycle.domain.work.detail import ci_checks_url, leading_run_names, with_leading
from tests.support.fake_store import FakeStore

PR = "https://github.com/o/r/pull/7"
SPEC_PR = "https://github.com/o/r/pull/3"


class FlowStub:
    def __init__(self, phase, detail=None):
        self._flow = Flow({"s": StepDef(owner="agent", detail=detail)})
        self._phase = phase

    def flow_for(self, node):
        return self._flow

    def phase_for(self, node):
        return self._phase


def keys(entries):
    return [e.key for e in entries]


def values(entries):
    return {e.key: e.value for e in entries}


def build(phase="code", detail=None, with_spec_run=False, pr=PR, branch="feat/x"):
    store = FakeStore()
    item = store.create_item("item", "desc", shortcode="OWN")
    pid = store.open_pass(item)
    if with_spec_run:
        spec_rid = store.open_run(item, pid, "spec")
        store.set_pr(spec_rid, SPEC_PR)
        store.close_run(spec_rid, "merged")
    rid = store.open_run(item, pid, phase)
    store.set_branch(rid, branch)
    store.set_pr(rid, pr)
    step = store.create_step(step="s", role="agent", parent=item)
    store.set_step_pass(step, pid)
    return store, item, step, FlowStub(phase, detail)


def resolve(store, step, flow, worktree="/wt/x", inputs=None):
    return StepDetail(store, flow).resolve(
        store.get_node(step), inputs or {}, [], worktree=worktree)[0]


class TestLeadingRunRows(unittest.TestCase):
    def test_run_rows_lead_the_declared_list(self):
        store, _item, step, flow = build(detail=("outcome", "report"))
        self.assertEqual(
            keys(resolve(store, step, flow)), ["pr", "branch", "worktree", "outcome", "report"])

    def test_a_declared_name_also_leading_is_shown_once_leading(self):
        store, _item, step, flow = build(detail=("pr", "in:report", "outcome"))
        self.assertEqual(
            keys(resolve(store, step, flow)),
            ["pr", "branch", "worktree", "in:report", "outcome"])

    def test_a_code_phase_step_links_back_to_the_merged_spec_pr(self):
        store, _item, step, flow = build(with_spec_run=True)
        entries = resolve(store, step, flow)
        self.assertEqual(keys(entries)[:4], ["pr", "spec-pr", "branch", "worktree"])
        self.assertEqual(values(entries)["spec-pr"], SPEC_PR)

    def test_a_spec_phase_step_has_no_spec_pr_row(self):
        store, _item, step, flow = build(phase="spec", with_spec_run=False)
        self.assertNotIn("spec-pr", keys(resolve(store, step, flow)))

    def test_a_pass_without_a_spec_run_has_no_spec_pr_row(self):
        store, _item, step, flow = build()
        self.assertNotIn("spec-pr", keys(resolve(store, step, flow)))

    def test_the_item_spec_artifact_adds_a_spec_row(self):
        store, item, step, flow = build()
        store.add_artifact(item, "spec", "lightcycle/x.md")
        entries = resolve(store, step, flow)
        self.assertEqual(keys(entries)[3], "spec")
        self.assertEqual(values(entries)["spec"], "lightcycle/x.md")

    def test_a_ci_judged_sha_on_the_step_adds_the_checks_url(self):
        store, _item, step, flow = build()
        store.add_artifact(step, "ci-judged-sha", "abc123", internal=True)
        entries = resolve(store, step, flow)
        self.assertEqual(values(entries)["ci-checks"], PR + "/checks?sha=abc123")

    def test_a_ci_judged_sha_on_the_previous_step_adds_the_checks_url(self):
        store, item, _step, flow = build()
        prior = store.create_step(step="s", role="agent", parent=item)
        store.add_artifact(prior, "ci-judged-sha", "def456", internal=True)
        step = store.create_step(step="s", role="agent", parent=item, previous=prior)
        store.set_step_pass(step, store.current_pass(item).id)
        self.assertEqual(
            values(resolve(store, step, flow))["ci-checks"], PR + "/checks?sha=def456")

    def test_no_ci_judged_sha_means_no_checks_row(self):
        store, _item, step, flow = build()
        self.assertNotIn("ci-checks", keys(resolve(store, step, flow)))

    def test_a_step_with_no_run_shows_what_it_showed_before(self):
        store = FakeStore()
        item = store.create_item("item", "desc", shortcode="OWN")
        step = store.create_step(step="s", role="agent", parent=item)
        flow = FlowStub(None, ("outcome", "report"))
        self.assertEqual(keys(resolve(store, step, flow)), ["outcome", "report"])


class TestLeadingRunNames(unittest.TestCase):
    def test_all_rows_in_order(self):
        self.assertEqual(
            leading_run_names(True, True, True),
            ("pr", "spec-pr", "branch", "worktree", "spec", "ci-checks"))

    def test_with_leading_drops_repeats_from_the_rest(self):
        self.assertEqual(with_leading(("pr", "branch"), ("branch", "outcome")), ("pr", "branch", "outcome"))

    def test_checks_url_needs_both_pr_and_sha(self):
        self.assertIsNone(ci_checks_url(None, "abc"))
        self.assertIsNone(ci_checks_url(PR, None))
