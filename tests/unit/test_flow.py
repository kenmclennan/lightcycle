import unittest

from the_grid.domain.flow import Flow, Transition
from the_grid.domain.task import Task

METAS = {
    "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
    "reviewer": {"model": "opus", "step": "review",
                 "routes": {"done": "open-pr", "rejected": "build"}},
    "pr-watcher": {"model": "sonnet", "step": "open-pr",
                   "routes": {"done": "ready-merge", "ci-failed": "build"}},
    "driver": {"model": "opus"},
}

# A flow that mixes automated agents (model + step) with human steps (step, no
# model). watch-pr is automated; ready-merge and cleanup are human steps.
HUMAN_METAS = {
    "watch-pr": {"model": "sonnet", "step": "watch-pr",
                 "routes": {"done": "ready-merge", "ci-failed": "build"}},
    "ready-merge": {"step": "ready-merge",
                    "routes": {"merged": "cleanup", "changes": "build"}},
    "cleanup": {"step": "cleanup"},
    "driver": {"model": "opus"},
}


class TestFlowAssembly(unittest.TestCase):
    def test_owner_and_routes(self):
        flow = Flow.assemble(METAS)
        self.assertEqual(flow.owner_of("build"), "coder")
        self.assertEqual(flow.owner_of("review"), "reviewer")
        self.assertEqual(flow.routes_map()["build"], {"done": "review"})

    def test_driver_owns_nothing(self):
        flow = Flow.assemble(METAS)
        self.assertEqual(set(flow.owner_map().values()), {"coder", "reviewer", "pr-watcher"})
        self.assertEqual(flow.steps(), ["build", "open-pr", "review"])


class TestHumanSteps(unittest.TestCase):
    def test_agent_step_owned_by_its_basename(self):
        self.assertEqual(Flow.assemble(HUMAN_METAS).owner_of("watch-pr"), "watch-pr")

    def test_no_model_step_owned_by_human(self):
        flow = Flow.assemble(HUMAN_METAS)
        self.assertEqual(flow.owner_of("ready-merge"), "human")
        self.assertEqual(flow.owner_of("cleanup"), "human")

    def test_routes_to_human_step(self):
        t = Flow.assemble(HUMAN_METAS).next("watch-pr", "done")
        self.assertEqual((t.to_step, t.to_role), ("ready-merge", "human"))


class TestNext(unittest.TestCase):
    def setUp(self):
        self.flow = Flow.assemble(METAS)

    def test_owned_target_derives_role(self):
        t = self.flow.next("build", "done")
        self.assertEqual((t.from_step, t.outcome, t.to_step, t.to_role),
                         ("build", "done", "review", "reviewer"))
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
        spec = self._t().next_task_spec(Task(id="t-1", title="build: make the thing"))
        self.assertEqual(spec["title"], "review: make the thing")
        self.assertEqual(spec["step"], "review")
        self.assertEqual(spec["role"], "reviewer")
        self.assertIsNone(spec["parent"])
        self.assertEqual(spec["deps"], ["t-1"])

    def test_next_task_spec_includes_parent_when_present(self):
        spec = self._t().next_task_spec(Task(id="t-1", title="build: x", parent="s-9"))
        self.assertEqual(spec["parent"], "s-9")

    def test_forward_note_provenance_format(self):
        self.assertEqual(self._t().forward_note("fix the tests"),
                         "from build (done): fix the tests")

    def test_forward_note_preserves_text_verbatim(self):
        t = self._t(from_step="review", outcome="rejected", to_step="build", to_role="coder")
        self.assertEqual(t.forward_note("add missing coverage"),
                         "from review (rejected): add missing coverage")


if __name__ == "__main__":
    unittest.main()
