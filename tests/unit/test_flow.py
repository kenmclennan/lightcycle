import unittest

from the_grid.core.flow import (advance_create_args, flow_next, load_flow,
                            ready_roles_from_beads)

METAS = {
    "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
    "reviewer": {"model": "opus", "step": "review",
                 "routes": {"done": "open-pr", "rejected": "build"}},
    "pr-watcher": {"model": "sonnet", "step": "open-pr",
                   "routes": {"done": "ready-merge", "ci-failed": "build"}},
    "driver": {"model": "opus"},
}


class TestLoadFlow(unittest.TestCase):
    def test_owner_and_routes(self):
        owner, routes = load_flow(METAS)
        self.assertEqual(owner["build"], "coder")
        self.assertEqual(owner["review"], "reviewer")
        self.assertNotIn(None, owner)  # driver has no step
        self.assertEqual(routes["build"], {"done": "review"})

    def test_driver_owns_nothing(self):
        owner, _ = load_flow(METAS)
        self.assertEqual(set(owner.values()), {"coder", "reviewer", "pr-watcher"})


class TestFlowNext(unittest.TestCase):
    def setUp(self):
        self.owner, self.routes = load_flow(METAS)

    def test_owned_target_derives_role(self):
        self.assertEqual(flow_next("build", "done", self.owner, self.routes),
                         ("review", "reviewer"))
        self.assertEqual(flow_next("review", "rejected", self.owner, self.routes),
                         ("build", "coder"))

    def test_unowned_target_is_human(self):
        self.assertEqual(flow_next("open-pr", "done", self.owner, self.routes),
                         ("ready-merge", "human"))

    def test_unknown_outcome_is_none(self):
        self.assertIsNone(flow_next("build", "banana", self.owner, self.routes))


class TestAdvanceCreateArgs(unittest.TestCase):
    def test_strips_step_prefix_and_keeps_deps(self):
        task = {"id": "t-1", "title": "build: make the thing"}
        args = advance_create_args(task, "review", "reviewer")
        self.assertEqual(args[1], "review: make the thing")
        self.assertIn("for:reviewer,step:review", args)
        self.assertIn("--deps", args)
        self.assertIn("t-1", args)
        self.assertNotIn("--parent", args)

    def test_includes_parent_when_present(self):
        task = {"id": "t-1", "title": "build: x", "parent": "s-9"}
        args = advance_create_args(task, "review", "reviewer")
        self.assertIn("--parent", args)
        self.assertIn("s-9", args)


class TestReadyRoles(unittest.TestCase):
    def test_dedupes_and_skips_human(self):
        beads = [{"labels": ["for:coder"]}, {"labels": ["for:coder"]},
                 {"labels": ["for:human"]}, {"labels": ["for:reviewer"]}]
        self.assertEqual(ready_roles_from_beads(beads), ["coder", "reviewer"])


if __name__ == "__main__":
    unittest.main()
