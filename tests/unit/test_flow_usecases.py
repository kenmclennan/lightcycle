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
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

_ROOT = str(Path(__file__).resolve().parents[2] / "lightcycle" / "library")


class _RealFs:
    def step_roles(self, project=None):
        return step_roles(_ROOT)

    def parse_step(self, role, project=None):
        return parse_step(_ROOT, role)

    def workflow_text(self, name, project=None):
        return workflow_text(_ROOT, name)


class _RealConfig:
    def default_workflow(self):
        return "standard"

    def default_workflow_for(self, project):
        return "standard"

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
    def __init__(self):
        self.removed = []

    def ensure(self, item):
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
        item = s.create_item("st", theme=s.create_theme("theme"))
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
        item = s.create_item("st", theme=s.create_theme("theme"))
        tid = s.create_step("open-pr: x", step="open-pr", role="open-pr", parent=item)
        resp = self._uc(s).execute(CompleteInput(step=tid, outcome="conflicted"))
        self.assertEqual(s.get_node(tid).state, "done")
        self.assertEqual(s.get_node(resp.next_step).step, "resolve")

    def test_done_outcome_still_requires_a_pr(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"))
        tid = s.create_step("open-pr: x", step="open-pr", role="open-pr", parent=item)
        with self.assertRaises(UseCaseError):
            self._uc(s).execute(CompleteInput(step=tid, outcome="done"))


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
        item = s.create_item("st", theme=s.create_theme("theme"))
        s.add_artifact(item, "spec", "specs/X.md")
        s.create_step("build: x", step="build", role="coder", parent=item)
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertEqual(resp.spec_path, os.path.join("/specs", "specs/X.md"))


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
        item = s.create_item("st", theme=s.create_theme("theme"))
        s.add_artifact(item, "pr", "https://github.com/x/y/pull/1")
        s.create_step("watch-pr: x", step="watch-pr", role="watch-pr", parent=item)
        resp = self._uc(s).execute(ClaimInput(role="watch-pr"))
        self.assertEqual(resp.config, {"ci-wait": "15m"})

    def test_omits_config_when_step_has_no_extra_frontmatter(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"))
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
