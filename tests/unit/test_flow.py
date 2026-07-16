import unittest

from lightcycle.domain.flow import Flow, Transition
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.work import Node
from tests.support.fake_fs import graph_text_from_metas


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
        self.assertEqual(flow.owner_of("build"), "coder")
        self.assertEqual(flow.owner_of("review"), "reviewer")
        self.assertEqual(flow.outcomes_for("build"), ["done"])
        self.assertEqual(flow.next("build", "done").to_step, "review")

    def test_driver_owns_nothing(self):
        flow = mkflow(METAS)
        self.assertEqual(
            {flow.owner_of(s) for s in flow.steps()}, {"coder", "reviewer", "pr-watcher"}
        )
        self.assertEqual(flow.steps(), ["build", "open-pr", "review"])


class TestHumanSteps(unittest.TestCase):
    def test_agent_step_owned_by_its_basename(self):
        self.assertEqual(mkflow(HUMAN_METAS).owner_of("watch-pr"), "watch-pr")

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
            (t.from_step, t.outcome, t.to_step, t.to_role), ("build", "done", "review", "reviewer")
        )
        t2 = self.flow.next("review", "rejected")
        self.assertEqual((t2.to_step, t2.to_role), ("build", "coder"))

    def test_unowned_target_is_human(self):
        t = self.flow.next("open-pr", "done")
        self.assertEqual((t.to_step, t.to_role), ("ready-merge", "human"))

    def test_unknown_outcome_is_none(self):
        self.assertIsNone(self.flow.next("build", "banana"))

    def test_outcomes_for(self):
        self.assertEqual(self.flow.outcomes_for("review"), ["done", "rejected"])


class TestTransition(unittest.TestCase):
    def _t(self, from_step="build", outcome="done", to_step="review", to_role="reviewer"):
        return Transition(from_step=from_step, outcome=outcome, to_step=to_step, to_role=to_role)

    def test_next_task_spec_strips_step_prefix_and_keeps_deps(self):
        spec = self._t().next_step_spec(Node(id="t-1", title="build: make the thing"))
        self.assertEqual(spec.title, "review: make the thing")
        self.assertEqual(spec.step, "review")
        self.assertEqual(spec.role, "reviewer")
        self.assertIsNone(spec.parent)
        self.assertEqual(spec.deps, ("t-1",))

    def test_next_task_spec_includes_parent_when_present(self):
        spec = self._t().next_step_spec(Node(id="t-1", title="build: x", parent="s-9"))
        self.assertEqual(spec.parent, "s-9")

    def test_next_task_spec_as_kwargs_matches_create_task(self):
        kw = self._t().next_step_spec(Node(id="t-1", title="build: x", parent="s-9")).as_kwargs()
        self.assertEqual(
            kw,
            {
                "title": "review: x",
                "step": "review",
                "role": "reviewer",
                "parent": "s-9",
                "deps": ["t-1"],
                "project": None,
                "goal": None,
            },
        )

    def test_forward_note_provenance_format(self):
        self.assertEqual(
            self._t().forward_note("fix the tests"), "from build (done): fix the tests"
        )

    def test_forward_note_preserves_text_verbatim(self):
        t = self._t(from_step="review", outcome="rejected", to_step="build", to_role="coder")
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
        metas = {"inspector": {"model": "sonnet", "step": "inspect", "on_theme_close": True}}
        flow = mkflow(metas)
        self.assertEqual(flow.hooks().get("on_theme_close"), ["inspect"])

    def test_falsy_hook_value_not_included(self):
        metas = {"role": {"model": "sonnet", "step": "s", "on_event": False}}
        self.assertEqual(mkflow(metas).hooks(), {})


class TestHookSteps(unittest.TestCase):
    def test_no_hooks_returns_empty(self):
        flow = mkflow(METAS)
        self.assertEqual(flow.hook_steps(), [])

    def test_known_hook_step_included(self):
        metas = {"auditor": {"model": "sonnet", "step": "audit", "on_theme_close": True}}
        flow = mkflow(metas)
        self.assertEqual(flow.hook_steps(), [("audit", "auditor")])

    def test_arbitrary_hook_name_included_generically(self):
        metas = {"deployer": {"model": "sonnet", "step": "deploy", "on_deploy_green": True}}
        flow = mkflow(metas)
        self.assertEqual(flow.hook_steps(), [("deploy", "deployer")])

    def test_step_flagged_by_multiple_hooks_appears_once(self):
        metas = {"auditor": {"model": "sonnet", "step": "audit",
                              "on_theme_close": True, "on_deploy_green": True}}
        flow = mkflow(metas)
        self.assertEqual(flow.hook_steps(), [("audit", "auditor")])

    def test_multiple_hook_steps_sorted(self):
        metas = {
            "beta": {"model": "sonnet", "step": "zz-step", "on_theme_close": True},
            "alpha": {"model": "sonnet", "step": "aa-step", "on_deploy_green": True},
        }
        steps = mkflow(metas).hook_steps()
        self.assertEqual([s for s, _ in steps], ["aa-step", "zz-step"])


if __name__ == "__main__":
    unittest.main()
