import os
import unittest
from pathlib import Path

from lightcycle.adapters.fsio import parse_step, step_roles, workflow_text
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import (
    AdvanceInput,
    AdvanceStepUseCase,
    BlockInput,
    BlockStepUseCase,
    ClaimInput,
    ClaimStepUseCase,
    CompleteInput,
    CompleteStepUseCase,
    FlowCheckInput,
    FlowCheckUseCase,
    UnblockInput,
    UnblockStepUseCase,
)
from lightcycle.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore

_ROOT = str(Path(__file__).resolve().parents[1] / "support" / "library")


class _RealFs:
    def step_roles(self, project=None):
        return step_roles(_ROOT)

    def parse_step(self, role, project=None):
        return parse_step(_ROOT, role)

    def workflow_text(self, name, project=None):
        return workflow_text(_ROOT, name)


class _RealConfig:
    def default_workflow(self):
        return "spec-driven"

    def default_workflow_for(self, project):
        return "spec-driven"

METAS = {
    "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
    "reviewer": {
        "model": "opus",
        "step": "review",
        "produces": {"pr": "required"},
        "routes": {"done": "open-pr", "rejected": "build"},
    },
    "pr-watcher": {
        "model": "sonnet",
        "step": "open-pr",
        "accepts": {"pr": "required"},
    },
}
SPEC_METAS = {
    "coder": {
        "model": "sonnet",
        "step": "build",
        "accepts": {"spec": "required"},
        "routes": {"done": "review"},
    },
}


def flow_for(metas, store):
    return FlowService(FakeFs(metas), store)


class FakeWorktrees:
    def __init__(self, ensure_error=None):
        self.removed = []
        self._ensure_error = ensure_error

    def ensure(self, item):
        if self._ensure_error is not None:
            raise self._ensure_error
        return None

    def item_branch(self, item):
        return None

    def remove(self, item):
        self.removed.append(item)


class FakeWorkers:
    def __init__(self):
        self.stamped = []

    def set_step(self, spawnid, step):
        self.stamped.append((spawnid, step))


class FakeConfig:
    def __init__(self, spawn=None):
        self._spawn = spawn

    def spawn_id(self):
        return self._spawn

    def specs_root(self):
        return "/specs"

    def projects_root(self):
        return "/projects"


class TestAdvanceTask(unittest.TestCase):
    def test_creates_next_task(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        resp = AdvanceStepUseCase(s, flow_for(METAS, s)).execute(
            AdvanceInput(step=bid, outcome="done")
        )
        nt = s.get_node(resp.next_step)
        self.assertEqual(nt.step, "review")
        self.assertEqual(nt.role, "reviewer")

    def test_unknown_outcome_returns_none(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        resp = AdvanceStepUseCase(s, flow_for(METAS, s)).execute(
            AdvanceInput(step=bid, outcome="nope")
        )
        self.assertIsNone(resp.next_step)


class TestCompleteTask(unittest.TestCase):
    def test_closes_and_advances(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        resp = CompleteStepUseCase(s, flow_for(METAS, s)).execute(
            CompleteInput(step=bid, outcome="done")
        )
        self.assertEqual(s.get_node(bid).state, "done")
        self.assertEqual(s.get_node(resp.next_step).step, "review")

    def test_invalid_outcome_raises(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        with self.assertRaises(UseCaseError):
            CompleteStepUseCase(s, flow_for(METAS, s)).execute(
                CompleteInput(step=bid, outcome="banana")
            )

    def test_missing_required_output_raises(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        rid = s.create_step("review: x", step="review", role="reviewer", parent=item)
        with self.assertRaises(UseCaseError):
            CompleteStepUseCase(s, flow_for(METAS, s)).execute(
                CompleteInput(step=rid, outcome="done")
            )

    def test_terminal_step_closes_without_routing(self):
        terminal_metas = {"finaliser": {"model": "sonnet", "step": "finalise"}}
        s = FakeStore()
        tid = s.create_step("finalise: x", step="finalise", role="finaliser")
        resp = CompleteStepUseCase(s, flow_for(terminal_metas, s)).execute(
            CompleteInput(step=tid, outcome="done")
        )
        self.assertEqual(s.get_node(tid).state, "done")
        self.assertIsNone(resp.next_step)

    def test_step_with_routes_unknown_outcome_still_errors(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        with self.assertRaises(UseCaseError):
            CompleteStepUseCase(s, flow_for(METAS, s)).execute(
                CompleteInput(step=bid, outcome="typo")
            )

    def test_declared_terminal_outcome_closes_silently_alongside_a_routed_one(self):
        metas = {"coder": {"model": "sonnet"}, "reviewer": {"model": "opus"}}
        graph_text = (
            "entry: build\n\n"
            "nodes:\n"
            "  build   coder\n"
            "  review  reviewer\n\n"
            "edges:\n"
            "  build  done   review\n"
            "  build  clean\n"
        )
        s = FakeStore()
        flow_svc = FlowService(FakeFs(metas, workflow=graph_text), s)
        bid = s.create_step("build: x", step="build", role="coder")
        resp = CompleteStepUseCase(s, flow_svc).execute(
            CompleteInput(step=bid, outcome="clean")
        )
        self.assertEqual(s.get_node(bid).state, "done")
        self.assertIsNone(resp.next_step)

    def test_unknown_stage_routes_to_human_instead_of_silent_close(self):
        s = FakeStore()
        rid = s.create_step("review-code: x", step="review-code", role="reviewer")
        resp = CompleteStepUseCase(s, flow_for(METAS, s)).execute(
            CompleteInput(step=rid, outcome="done")
        )
        self.assertIsNone(resp.next_step)
        node = s.get_node(rid)
        self.assertNotEqual(node.state, "done")
        self.assertEqual(node.role, "human")
        self.assertIn("review-code", node.notes or "")

    def test_terminal_step_with_required_produce_does_not_demand_it(self):
        terminal_metas = {
            "finaliser": {
                "model": "sonnet",
                "step": "finalise",
                "produces": {"widget": "required"},
            },
        }
        s = FakeStore()
        tid = s.create_step("finalise: x", step="finalise", role="finaliser")
        resp = CompleteStepUseCase(s, flow_for(terminal_metas, s)).execute(
            CompleteInput(step=tid, outcome="done")
        )
        self.assertEqual(s.get_node(tid).state, "done")
        self.assertIsNone(resp.next_step)


class TestCompleteStepEngineAudit(unittest.TestCase):
    def _uc(self, store):
        return CompleteStepUseCase(store, flow_for(METAS, store), FakeWorktrees())

    def _retro_batch(self, store):
        item = store.create_item("pending-feedback")
        store.label_add(item, "retro-origin")
        return item

    def _reviewed_item(self, store, repo=None, reflection=True):
        item = store.create_item("reviewed")
        store.close(item, "done")
        if repo is not None:
            store.add_artifact(item, "repo", repo)
        if reflection:
            k = store.create_step("build: x", step="build", role="coder", parent=item)
            store.close(k, "done")
            store.add_artifact(k, "reflection", "fb")
        return item

    def _audit_step(self, store, batch):
        return store.create_step(
            "audit: pending-feedback", step="audit", role="audit", parent=batch)

    def test_findings_marks_retroed_and_surfaces_a_human_inbox_step(self):
        s = FakeStore()
        reviewed = self._reviewed_item(s)
        batch = self._retro_batch(s)
        aid = self._audit_step(s, batch)
        resp = self._uc(s).execute(CompleteInput(step=aid, outcome="findings", note="the digest"))
        self.assertIsNone(resp.next_step)
        self.assertNotIn(reviewed, [i.id for i in s.closed_unretroed_items()])
        human = [c for c in s.children(batch) if c.role == "human"]
        self.assertEqual(len(human), 1)
        self.assertTrue(human[0].attention)
        self.assertEqual(human[0].state, "ready")

    def test_clean_marks_retroed_with_no_inbox_step(self):
        s = FakeStore()
        reviewed = self._reviewed_item(s)
        batch = self._retro_batch(s)
        aid = self._audit_step(s, batch)
        resp = self._uc(s).execute(CompleteInput(step=aid, outcome="clean"))
        self.assertIsNone(resp.next_step)
        self.assertNotIn(reviewed, [i.id for i in s.closed_unretroed_items()])
        self.assertEqual([c for c in s.children(batch) if c.role == "human"], [])

    def test_non_audit_step_completion_does_not_mark_retroed(self):
        s = FakeStore()
        reviewed = self._reviewed_item(s)
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        bid = s.create_step("build: x", step="build", role="coder", parent=item)
        CompleteStepUseCase(s, flow_for(METAS, s)).execute(CompleteInput(step=bid, outcome="done"))
        self.assertIn(reviewed, [i.id for i in s.closed_unretroed_items()])

    def test_item_with_no_reflection_is_not_marked_retroed(self):
        s = FakeStore()
        no_feedback = self._reviewed_item(s, reflection=False)
        batch = self._retro_batch(s)
        aid = self._audit_step(s, batch)
        self._uc(s).execute(CompleteInput(step=aid, outcome="clean"))
        self.assertIn(no_feedback, [i.id for i in s.closed_unretroed_items()])

    def test_feedback_bearing_items_with_different_repos_are_all_marked_retroed(self):
        s = FakeStore()
        one = self._reviewed_item(s, repo="lightcycle")
        two = self._reviewed_item(s, repo="saga")
        three = self._reviewed_item(s)
        batch = self._retro_batch(s)
        aid = self._audit_step(s, batch)
        self._uc(s).execute(CompleteInput(step=aid, outcome="clean"))
        remaining = [i.id for i in s.closed_unretroed_items()]
        self.assertNotIn(one, remaining)
        self.assertNotIn(two, remaining)
        self.assertNotIn(three, remaining)


class TestCompleteStepCascadeClose(unittest.TestCase):
    TERMINAL_METAS = {"finaliser": {"model": "sonnet", "step": "finalise"}}

    def test_terminal_step_auto_closes_item_and_removes_worktree(self):
        s = FakeStore()
        item = s.create_item("it", theme=s.create_theme("theme"))
        tid = s.create_step("finalise: x", step="finalise", role="finaliser", parent=item)
        wt = FakeWorktrees()
        CompleteStepUseCase(s, flow_for(self.TERMINAL_METAS, s), wt).execute(
            CompleteInput(step=tid, outcome="done")
        )
        self.assertEqual(s.get_node(item).state, "done")
        self.assertEqual(wt.removed, [item])

    def test_intermediate_step_does_not_close_item(self):
        s = FakeStore()
        item = s.create_item("it", theme=s.create_theme("theme"))
        bid = s.create_step("build: x", step="build", role="coder", parent=item)
        CompleteStepUseCase(s, flow_for(METAS, s)).execute(
            CompleteInput(step=bid, outcome="done")
        )
        self.assertEqual(s.get_node(item).state, "in_progress")

    def test_last_open_item_close_auto_closes_theme(self):
        s = FakeStore()
        theme = s.create_theme("theme")
        s.close(s.create_item("done already", theme=theme), "done")
        item = s.create_item("it", theme=theme)
        tid = s.create_step("finalise: x", step="finalise", role="finaliser", parent=item)
        CompleteStepUseCase(s, flow_for(self.TERMINAL_METAS, s), FakeWorktrees()).execute(
            CompleteInput(step=tid, outcome="done")
        )
        self.assertEqual(s.get_node(item).state, "done")
        self.assertEqual(s.get_node(theme).state, "done")

    def test_theme_with_still_open_item_stays_open(self):
        s = FakeStore()
        theme = s.create_theme("theme")
        item = s.create_item("it", theme=theme)
        tid = s.create_step("finalise: x", step="finalise", role="finaliser", parent=item)
        s.create_item("still open", theme=theme)
        CompleteStepUseCase(s, flow_for(self.TERMINAL_METAS, s), FakeWorktrees()).execute(
            CompleteInput(step=tid, outcome="done")
        )
        self.assertEqual(s.get_node(item).state, "done")
        self.assertEqual(s.get_node(theme).state, "in_progress")


class TestCompleteTaskOutcomeScopedProduce(unittest.TestCase):
    DIVERSION_METAS = {
        "alpha-role": {
            "model": "sonnet",
            "step": "alpha",
            "produces": {"widget": "required"},
            "routes": {"forward": "beta", "sideways": "gamma"},
        },
        "beta-role": {"model": "sonnet", "step": "beta", "accepts": {"widget": "required"}},
        "gamma-role": {"model": "sonnet", "step": "gamma"},
    }

    def test_blocked_on_outcome_whose_target_requires_the_produce(self):
        s = FakeStore()
        aid = s.create_step("alpha: x", step="alpha", role="alpha-role")
        with self.assertRaises(UseCaseError):
            CompleteStepUseCase(s, flow_for(self.DIVERSION_METAS, s)).execute(
                CompleteInput(step=aid, outcome="forward")
            )

    def test_allowed_on_outcome_whose_target_does_not_require_the_produce(self):
        s = FakeStore()
        aid = s.create_step("alpha: x", step="alpha", role="alpha-role")
        resp = CompleteStepUseCase(s, flow_for(self.DIVERSION_METAS, s)).execute(
            CompleteInput(step=aid, outcome="sideways")
        )
        self.assertEqual(s.get_node(aid).state, "done")
        self.assertEqual(s.get_node(resp.next_step).step, "gamma")


class TestOpenPrConflictRouteWithRealSteps(unittest.TestCase):
    def _uc(self, store):
        return CompleteStepUseCase(store, FlowService(_RealFs(), store, _RealConfig()))

    def test_conflicted_outcome_closes_without_a_pr_and_routes_to_resolve(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        tid = s.create_step("code-open-pr: x", step="code-open-pr", role="open-pr", parent=item)
        resp = self._uc(s).execute(CompleteInput(step=tid, outcome="conflicted"))
        self.assertEqual(s.get_node(tid).state, "done")
        self.assertEqual(s.get_node(resp.next_step).step, "resolve-conflict")

    def test_done_outcome_still_requires_a_pr(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        tid = s.create_step("code-open-pr: x", step="code-open-pr", role="open-pr", parent=item)
        with self.assertRaises(UseCaseError):
            self._uc(s).execute(CompleteInput(step=tid, outcome="done"))


class TestCiFailedCapRouting(unittest.TestCase):
    GRAPH_TEXT = (
        "entry: build\n"
        "\n"
        "nodes:\n"
        "  build   coder\n"
        "  watch   watcher\n"
        "\n"
        "edges:\n"
        "  build  done       watch\n"
        "  watch  ci-failed  build\n"
        "  watch  done       ship\n"
        "\n"
        "hooks:\n"
        "  ci_failed_cap  watch  ci-failed  2  escalate-step\n"
    )
    METAS = {
        "coder": {"model": "sonnet"},
        "watcher": {"model": "sonnet"},
    }

    def _uc(self, store):
        return CompleteStepUseCase(
            store, FlowService(FakeFs(self.METAS, workflow=self.GRAPH_TEXT), store)
        )

    def _fail_n_times(self, store, item, n):
        for _ in range(n):
            old = store.create_step("watch: x", step="watch", role="watcher", parent=item)
            store.close(old, "ci-failed")

    def test_under_cap_routes_normally(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        self._fail_n_times(s, item, 1)
        wid = s.create_step("watch: x", step="watch", role="watcher", parent=item)
        resp = self._uc(s).execute(CompleteInput(step=wid, outcome="ci-failed"))
        self.assertEqual(s.get_node(wid).outcome, "ci-failed")
        self.assertEqual(s.get_node(resp.next_step).step, "build")

    def test_at_cap_escalates_instead_of_looping(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        self._fail_n_times(s, item, 2)
        wid = s.create_step("watch: x", step="watch", role="watcher", parent=item)
        resp = self._uc(s).execute(CompleteInput(step=wid, outcome="ci-failed"))
        self.assertEqual(s.get_node(wid).outcome, "ci-failed")
        self.assertEqual(s.get_node(resp.next_step).step, "escalate-step")
        self.assertEqual(s.get_node(resp.next_step).role, "human")

    def test_cap_counts_only_this_item(self):
        s = FakeStore()
        other = s.create_item("other", theme=s.create_theme("theme"))
        self._fail_n_times(s, other, 2)
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        wid = s.create_step("watch: x", step="watch", role="watcher", parent=item)
        resp = self._uc(s).execute(CompleteInput(step=wid, outcome="ci-failed"))
        self.assertEqual(s.get_node(resp.next_step).step, "build")

    def test_cap_counts_only_the_matching_outcome(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        self._fail_n_times(s, item, 3)
        wid = s.create_step("watch: x", step="watch", role="watcher", parent=item)
        resp = self._uc(s).execute(CompleteInput(step=wid, outcome="done"))
        self.assertEqual(s.get_node(resp.next_step).step, "ship")

    def test_repeated_done_never_escalates_even_past_cap(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        for _ in range(2):
            old = s.create_step("watch: x", step="watch", role="watcher", parent=item)
            s.close(old, "done")
        wid = s.create_step("watch: x", step="watch", role="watcher", parent=item)
        resp = self._uc(s).execute(CompleteInput(step=wid, outcome="done"))
        self.assertEqual(s.get_node(resp.next_step).step, "ship")

    def test_note_still_forwards_to_the_escalated_step(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        self._fail_n_times(s, item, 2)
        wid = s.create_step("watch: x", step="watch", role="watcher", parent=item)
        resp = self._uc(s).execute(
            CompleteInput(step=wid, outcome="ci-failed", note="job X / test Y failed")
        )
        self.assertIn("job X / test Y failed", s.get_node(resp.next_step).notes)

    def test_no_cap_declared_never_escalates(self):
        no_cap_metas = {"coder": {"model": "sonnet"}, "watcher": {"model": "sonnet"}}
        no_cap_graph = (
            "entry: build\n\nnodes:\n  build  coder\n  watch  watcher\n\n"
            "edges:\n  build  done       watch\n  watch  ci-failed  build\n"
        )
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        uc = CompleteStepUseCase(s, FlowService(FakeFs(no_cap_metas, workflow=no_cap_graph), s))
        for _ in range(5):
            old = s.create_step("watch: x", step="watch", role="watcher", parent=item)
            s.close(old, "ci-failed")
        wid = s.create_step("watch: x", step="watch", role="watcher", parent=item)
        resp = uc.execute(CompleteInput(step=wid, outcome="ci-failed"))
        self.assertEqual(s.get_node(resp.next_step).step, "build")


class TestCiFailedCapAdvancePath(unittest.TestCase):
    GRAPH_TEXT = TestCiFailedCapRouting.GRAPH_TEXT
    METAS = TestCiFailedCapRouting.METAS

    def _fail_n_times(self, store, item, n):
        for _ in range(n):
            old = store.create_step("watch: x", step="watch", role="watcher", parent=item)
            store.close(old, "ci-failed")

    def test_advance_under_cap_routes_normally(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        self._fail_n_times(s, item, 1)
        wid = s.create_step("watch: x", step="watch", role="watcher", parent=item)
        flow = FlowService(FakeFs(self.METAS, workflow=self.GRAPH_TEXT), s)
        resp = AdvanceStepUseCase(s, flow).execute(AdvanceInput(step=wid, outcome="ci-failed"))
        self.assertEqual(s.get_node(resp.next_step).step, "build")

    def test_advance_at_cap_escalates_instead_of_looping(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        self._fail_n_times(s, item, 2)
        wid = s.create_step("watch: x", step="watch", role="watcher", parent=item)
        flow = FlowService(FakeFs(self.METAS, workflow=self.GRAPH_TEXT), s)
        resp = AdvanceStepUseCase(s, flow).execute(AdvanceInput(step=wid, outcome="ci-failed"))
        self.assertEqual(s.get_node(resp.next_step).step, "escalate-step")
        self.assertEqual(s.get_node(resp.next_step).role, "human")


class TestAdvanceAndCompleteAgreeOnCappedTransitions(unittest.TestCase):
    GRAPH_TEXT = TestCiFailedCapRouting.GRAPH_TEXT
    METAS = TestCiFailedCapRouting.METAS

    def _fail_n_times(self, store, item, n):
        for _ in range(n):
            old = store.create_step("watch: x", step="watch", role="watcher", parent=item)
            store.close(old, "ci-failed")

    def _setup(self, prior_failures):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        self._fail_n_times(s, item, prior_failures)
        wid = s.create_step("watch: x", step="watch", role="watcher", parent=item)
        flow = FlowService(FakeFs(self.METAS, workflow=self.GRAPH_TEXT), s)
        return s, wid, flow

    def test_below_cap_same_next_step_both_paths(self):
        s, wid, flow = self._setup(prior_failures=1)
        advanced = AdvanceStepUseCase(s, flow).execute(AdvanceInput(step=wid, outcome="ci-failed"))
        s2, wid2, flow2 = self._setup(prior_failures=1)
        completed = CompleteStepUseCase(s2, flow2).execute(
            CompleteInput(step=wid2, outcome="ci-failed")
        )
        self.assertEqual(
            s.get_node(advanced.next_step).step, s2.get_node(completed.next_step).step
        )

    def test_at_cap_same_next_step_both_paths(self):
        s, wid, flow = self._setup(prior_failures=2)
        advanced = AdvanceStepUseCase(s, flow).execute(AdvanceInput(step=wid, outcome="ci-failed"))
        s2, wid2, flow2 = self._setup(prior_failures=2)
        completed = CompleteStepUseCase(s2, flow2).execute(
            CompleteInput(step=wid2, outcome="ci-failed")
        )
        self.assertEqual(s.get_node(advanced.next_step).step, "escalate-step")
        self.assertEqual(
            s.get_node(advanced.next_step).step, s2.get_node(completed.next_step).step
        )


class TestCiFailedCapWithRealSteps(unittest.TestCase):
    def _uc(self, store):
        return CompleteStepUseCase(store, FlowService(_RealFs(), store, _RealConfig()))

    def test_under_cap_routes_to_write_code(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        wid = s.create_step("watch-ci: x", step="watch-ci", role="watch-ci", parent=item)
        resp = self._uc(s).execute(CompleteInput(step=wid, outcome="ci-failed"))
        self.assertEqual(s.get_node(wid).outcome, "ci-failed")
        self.assertEqual(s.get_node(resp.next_step).step, "write-code")

    def test_cap_reached_escalates_to_review_ci(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        for _ in range(3):
            old = s.create_step("watch-ci: x", step="watch-ci", role="watch-ci", parent=item)
            s.close(old, "ci-failed")
        wid = s.create_step("watch-ci: x", step="watch-ci", role="watch-ci", parent=item)
        resp = self._uc(s).execute(CompleteInput(step=wid, outcome="ci-failed"))
        self.assertEqual(s.get_node(resp.next_step).step, "review-ci")
        self.assertEqual(s.get_node(resp.next_step).role, "human")


class TestClaimTask(unittest.TestCase):
    def _uc(self, store, config=None):
        return ClaimStepUseCase(
            store, flow_for(METAS, store), FakeWorktrees(), FakeWorkers(), config or FakeConfig()
        )

    def test_claims_ready_task(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertEqual(resp.view.step.id, bid)

    def test_records_model_from_role_frontmatter(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        self._uc(s).execute(ClaimInput(role="coder"))
        self.assertEqual(s.get_node(bid).model, "sonnet")

    def test_nothing_ready_returns_none(self):
        self.assertIsNone(self._uc(FakeStore()).execute(ClaimInput(role="coder")))

    def test_stamps_spawn_id_when_present(self):
        s = FakeStore()
        s.create_step("build: x", step="build", role="coder")
        workers = FakeWorkers()
        ClaimStepUseCase(
            s, flow_for(METAS, s), FakeWorktrees(), workers, FakeConfig(spawn="sp1")
        ).execute(ClaimInput(role="coder"))
        self.assertEqual(len(workers.stamped), 1)

    def test_missing_required_input_routes_to_human(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        resp = ClaimStepUseCase(
            s, flow_for(SPEC_METAS, s), FakeWorktrees(), FakeWorkers(), FakeConfig()
        ).execute(ClaimInput(role="coder"))
        self.assertIsNone(resp)
        self.assertEqual(s.get_node(bid).role, "human")

    def test_resolves_spec_path_against_specs_root(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        s.add_artifact(item, "spec", "specs/X.md")
        s.create_step("build: x", step="build", role="coder", parent=item)
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertEqual(resp.spec_path, os.path.join("/specs", "specs/X.md"))

    def test_resolves_project_subdir_spec_path_against_specs_root(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        s.add_artifact(item, "spec", "myproject/LC-1-my-spec.md")
        s.create_step("build: x", step="build", role="coder", parent=item)
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertEqual(
            resp.spec_path, os.path.join("/specs", "myproject/LC-1-my-spec.md")
        )

    def test_resolves_brief_content_from_artifact(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        s.add_artifact(item, "brief", "the brief's literal text")
        s.create_step("build: x", step="build", role="coder", parent=item)
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertEqual(resp.brief, "the brief's literal text")

    def test_omits_brief_when_no_brief_artifact(self):
        s = FakeStore()
        s.create_step("build: x", step="build", role="coder")
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertIsNone(resp.brief)

    def test_resolves_repo_path_against_projects_root(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        s.add_artifact(item, "repo", "app")
        s.create_step("build: x", step="build", role="coder", parent=item)
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertEqual(resp.repo_path, os.path.join("/projects", "app"))

    def test_omits_repo_path_when_no_repo_artifact(self):
        s = FakeStore()
        s.create_step("build: x", step="build", role="coder")
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertIsNone(resp.repo_path)

    def test_claim_exposes_the_code_phase_by_default(self):
        s = FakeStore()
        s.create_step("build: x", step="build", role="coder")
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertEqual(resp.phase, "code")

    def test_claim_exposes_the_spec_phase_for_a_specs_workspace_workflow(self):
        s = FakeStore()
        s.create_step("build: x", step="build", role="coder")
        fs = FakeFs(METAS, workflow="workspace: specs\n\n" + graph_text_from_metas(METAS))
        resp = ClaimStepUseCase(
            s, FlowService(fs, s), FakeWorktrees(), FakeWorkers(), FakeConfig()
        ).execute(ClaimInput(role="coder"))
        self.assertEqual(resp.phase, "spec")

    def test_ensure_failure_rolls_back_claim_to_ready(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        uc = ClaimStepUseCase(
            s, flow_for(METAS, s), FakeWorktrees(ensure_error=RuntimeError("boom")),
            FakeWorkers(), FakeConfig()
        )
        with self.assertRaises(RuntimeError):
            uc.execute(ClaimInput(role="coder"))
        t = s.get_node(bid)
        self.assertEqual(str(t.state), "ready")
        self.assertIsNone(t.claimed_by)


class TestClaimConfigWithRealSteps(unittest.TestCase):
    def _uc(self, store):
        return ClaimStepUseCase(
            store,
            FlowService(_RealFs(), store, _RealConfig()),
            FakeWorktrees(),
            FakeWorkers(),
            FakeConfig(),
        )

    def test_surfaces_extra_frontmatter_as_config(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        s.add_artifact(item, "pr", "https://github.com/x/y/pull/1")
        s.create_step("watch-ci: x", step="watch-ci", role="watch-ci", parent=item)
        resp = self._uc(s).execute(ClaimInput(role="watch-ci"))
        self.assertEqual(resp.config, {"ci-wait": "15m"})

    def test_omits_config_when_step_has_no_extra_frontmatter(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"), workflow="spec-driven")
        s.add_artifact(item, "spec", "specs/X.md")
        s.create_step("build: x", step="build", role="coder", parent=item)
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertIsNone(resp.config)


class TestBlockTask(unittest.TestCase):
    def test_routes_to_human_with_resume(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        BlockStepUseCase(s).execute(BlockInput(step=bid, needs="decide X", branch="feat/y"))
        t = s.get_node(bid)
        self.assertEqual(t.role, "human")
        self.assertEqual(t.needs, "decide X")


class TestFlowCheck(unittest.TestCase):
    def test_returns_owner_routes_and_analysis(self):
        s = FakeStore()
        resp = FlowCheckUseCase(flow_for(METAS, s)).execute(FlowCheckInput())
        self.assertEqual(resp.owner["build"], "coder")
        self.assertEqual(resp.routes["build"], {"done": "review"})
        self.assertIn("ok", resp.analysis)
        self.assertEqual(resp.hooks, {})

    def test_hooks_surfaced_from_arbitrary_on_key(self):
        metas = {"deployer": {"model": "sonnet", "step": "deploy", "on_ship_it": True}}
        s = FakeStore()
        resp = FlowCheckUseCase(flow_for(metas, s)).execute(FlowCheckInput())
        self.assertEqual(resp.hooks, {"on_ship_it": ["deploy"]})


class TestUnblockTask(unittest.TestCase):
    def test_flips_back_to_agent_role(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="human")
        resp = UnblockStepUseCase(s, flow_for(METAS, s)).execute(UnblockInput(step=bid))
        self.assertEqual(resp.role, "coder")
        self.assertEqual(s.get_node(bid).role, "coder")

    def test_no_agent_owner_raises(self):
        s = FakeStore()
        bid = s.create_step("a todo", role="human")
        with self.assertRaises(UseCaseError):
            UnblockStepUseCase(s, flow_for(METAS, s)).execute(UnblockInput(step=bid))

    def test_clears_needs_and_blocked_note(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        BlockStepUseCase(s).execute(BlockInput(step=bid, needs="confirm approach"))
        UnblockStepUseCase(s, flow_for(METAS, s)).execute(UnblockInput(step=bid))
        t = s.get_node(bid)
        self.assertIsNone(t.needs)
        self.assertNotIn("BLOCKED:", t.notes or "")

    def test_preserves_notes_unrelated_to_block(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="coder")
        s.note(bid, "from review: lgtm")
        BlockStepUseCase(s).execute(BlockInput(step=bid, needs="confirm approach"))
        UnblockStepUseCase(s, flow_for(METAS, s)).execute(UnblockInput(step=bid))
        t = s.get_node(bid)
        self.assertIn("from review: lgtm", t.notes or "")
        self.assertNotIn("BLOCKED:", t.notes or "")


if __name__ == "__main__":
    unittest.main()
