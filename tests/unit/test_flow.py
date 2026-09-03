import unittest

from lightcycle.domain.flow import Flow, Transition
from lightcycle.domain.flow.graph import parse_graph
from tests.support.fake_fs import graph_text_from_metas
from tests.support.factories import make_step


def mkflow(metas):
    return Flow.from_graph(parse_graph(graph_text_from_metas(metas)), metas)

METAS = {
    "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
    "reviewer": {
        "model": "opus",
        "step": "review",
        "routes": {"done": "open-pr", "rejected": "build"},
    },
    "pr-watcher": {
        "model": "sonnet",
        "step": "open-pr",
        "routes": {"done": "ready-merge", "ci-failed": "build"},
    },
    "driver": {"model": "opus"},
}

HUMAN_METAS = {
    "watch-pr": {
        "model": "sonnet",
        "step": "watch-pr",
        "routes": {"done": "ready-merge", "ci-failed": "build"},
    },
    "ready-merge": {"step": "ready-merge", "routes": {"merged": "cleanup", "changes": "build"}},
    "cleanup": {"step": "cleanup"},
    "driver": {"model": "opus"},
}


class TestFlowAssembly(unittest.TestCase):
    def test_owner_and_routes(self):
        flow = mkflow(METAS)
        self.assertEqual(flow.owner_of("build"), "agent")
        self.assertEqual(flow.owner_of("review"), "agent")
        self.assertEqual(flow.outcomes_for("build"), ["done"])
        self.assertEqual(flow.next("build", "done").to_step, "review")

    def test_every_owned_stage_collapses_to_the_one_agent_role(self):
        flow = mkflow(METAS)
        self.assertEqual({flow.owner_of(s) for s in flow.steps()}, {"agent"})
        self.assertEqual(flow.steps(), ["build", "open-pr", "review"])


class TestHumanSteps(unittest.TestCase):
    def test_a_stage_with_a_model_is_owned_by_the_agent_role_not_its_step_file(self):
        self.assertEqual(mkflow(HUMAN_METAS).owner_of("watch-pr"), "agent")

    def test_no_model_step_owned_by_human(self):
        flow = mkflow(HUMAN_METAS)
        self.assertEqual(flow.owner_of("ready-merge"), "human")
        self.assertEqual(flow.owner_of("cleanup"), "human")

    def test_routes_to_human_step(self):
        t = mkflow(HUMAN_METAS).next("watch-pr", "done")
        self.assertEqual((t.to_step, t.to_role), ("ready-merge", "human"))


class TestNext(unittest.TestCase):
    def setUp(self):
        self.flow = mkflow(METAS)

    def test_owned_target_derives_role(self):
        t = self.flow.next("build", "done")
        self.assertEqual(
            (t.from_step, t.outcome, t.to_step, t.to_role), ("build", "done", "review", "agent")
        )
        t2 = self.flow.next("review", "rejected")
        self.assertEqual((t2.to_step, t2.to_role), ("build", "agent"))

    def test_unowned_target_is_human(self):
        t = self.flow.next("open-pr", "done")
        self.assertEqual((t.to_step, t.to_role), ("ready-merge", "human"))

    def test_unknown_outcome_is_none(self):
        self.assertIsNone(self.flow.next("build", "banana"))

    def test_outcomes_for(self):
        self.assertEqual(self.flow.outcomes_for("review"), ["done", "rejected"])


class TestTransition(unittest.TestCase):
    def _t(self, from_step="build", outcome="done", to_step="review", to_role="agent"):
        return Transition(from_step=from_step, outcome=outcome, to_step=to_step, to_role=to_role)

    def test_next_task_spec_uses_the_given_item_title_and_keeps_deps(self):
        spec = self._t().next_step_spec(make_step(id="t-1", title="build: some stale title"), "make the thing")
        self.assertEqual(spec.title, "review: make the thing")
        self.assertEqual(spec.step, "review")
        self.assertEqual(spec.role, "agent")
        self.assertEqual(spec.parent, "i-1")
        self.assertEqual(spec.deps, ("t-1",))

    def test_next_task_spec_ignores_the_steps_own_title_entirely(self):
        spec = self._t().next_step_spec(
            make_step(id="t-1", title="build: consolidated sweep - see PR #349"), "fix the bug"
        )
        self.assertEqual(spec.title, "review: fix the bug")

    def test_next_task_spec_includes_parent_when_present(self):
        spec = self._t().next_step_spec(make_step(id="t-1", title="build: x", parent="s-9"), "x")
        self.assertEqual(spec.parent, "s-9")

    def test_next_task_spec_as_kwargs_matches_create_task(self):
        kw = self._t().next_step_spec(make_step(id="t-1", title="build: x", parent="s-9"), "x").as_kwargs()
        self.assertEqual(
            kw,
            {
                "title": "review: x",
                "step": "review",
                "role": "agent",
                "parent": "s-9",
                "deps": ["t-1"],
            },
        )

    def test_forward_note_provenance_format(self):
        self.assertEqual(
            self._t().forward_note("fix the tests"), "from build (done): fix the tests"
        )

    def test_forward_note_preserves_text_verbatim(self):
        t = self._t(from_step="review", outcome="rejected", to_step="build", to_role="agent")
        self.assertEqual(
            t.forward_note("add missing coverage"), "from review (rejected): add missing coverage"
        )


class TestHooks(unittest.TestCase):
    def test_no_hooks_returns_empty(self):
        flow = mkflow(METAS)
        self.assertEqual(flow.hooks(), {})

    def test_arbitrary_hook_name_surfaced_generically(self):
        metas = {"deployer": {"model": "sonnet", "step": "deploy", "on_deploy_green": True}}
        flow = mkflow(metas)
        self.assertEqual(flow.hooks(), {"on_deploy_green": ["deploy"]})


    def test_multiple_distinct_hooks_both_present(self):
        metas = {"role": {"model": "sonnet", "step": "s", "on_event_a": True, "on_event_b": "x"}}
        hooks = mkflow(metas).hooks()
        self.assertIn("on_event_a", hooks)
        self.assertIn("on_event_b", hooks)

    def test_known_hooks_also_appear_generically(self):
        metas = {"inspector": {"model": "sonnet", "step": "inspect", "on_deploy_green": True}}
        flow = mkflow(metas)
        self.assertEqual(flow.hooks().get("on_deploy_green"), ["inspect"])

    def test_falsy_hook_value_not_included(self):
        metas = {"role": {"model": "sonnet", "step": "s", "on_event": False}}
        self.assertEqual(mkflow(metas).hooks(), {})


class TestHookSteps(unittest.TestCase):
    def test_no_hooks_returns_empty(self):
        flow = mkflow(METAS)
        self.assertEqual(flow.hook_steps(), [])

    def test_known_hook_step_included(self):
        metas = {"auditor": {"model": "sonnet", "step": "audit", "on_deploy_green": True}}
        flow = mkflow(metas)
        self.assertEqual(flow.hook_steps(), ["audit"])

    def test_arbitrary_hook_name_included_generically(self):
        metas = {"deployer": {"model": "sonnet", "step": "deploy", "on_deploy_green": True}}
        flow = mkflow(metas)
        self.assertEqual(flow.hook_steps(), ["deploy"])

    def test_step_flagged_by_multiple_hooks_appears_once(self):
        metas = {"auditor": {"model": "sonnet", "step": "audit",
                              "on_deploy_green": True, "on_release_cut": True}}
        flow = mkflow(metas)
        self.assertEqual(flow.hook_steps(), ["audit"])

    def test_multiple_hook_steps_sorted(self):
        metas = {
            "beta": {"model": "sonnet", "step": "zz-step", "on_deploy_green": True},
            "alpha": {"model": "sonnet", "step": "aa-step", "on_deploy_green": True},
        }
        self.assertEqual(mkflow(metas).hook_steps(), ["aa-step", "zz-step"])


if __name__ == "__main__":
    unittest.main()
