import unittest

from the_grid.core.contracts import (FILE_PROVIDES, analyze_flow, guaranteed_artifacts,
                                 optional_inputs, required_inputs, required_outputs)
from the_grid.core.flow import load_flow

CONTRACT_METAS = {
    "coder": {"step": "build", "accepts": {"spec": "required", "branch": "optional"},
              "produces": {"branch": "required"}, "routes": {"done": "review"}},
    "reviewer": {"step": "review", "accepts": {"spec": "required", "branch": "required"},
                 "routes": {"done": "open-pr", "rejected": "build"}},
    "pr-watcher": {"step": "open-pr", "accepts": {"branch": "required"},
                   "produces": {"pr": "required"},
                   "routes": {"done": "ready-merge", "ci-failed": "build"}},
}


class TestArtifactTypes(unittest.TestCase):
    def test_required_optional_split(self):
        meta = {"accepts": {"spec": "required", "branch": "optional"}}
        self.assertEqual(required_inputs(meta), {"spec"})
        self.assertEqual(optional_inputs(meta), {"branch"})

    def test_produces(self):
        self.assertEqual(required_outputs({"produces": {"branch": "required"}}), {"branch"})

    def test_no_block_is_empty(self):
        self.assertEqual(required_inputs({}), set())


class TestGuaranteed(unittest.TestCase):
    def test_entry_step_guarantees_file_provides(self):
        owner, routes = load_flow(CONTRACT_METAS)
        prod = {"build": {"branch"}, "review": set(), "open-pr": {"pr"}}
        ga = guaranteed_artifacts(["build", "review", "open-pr"], routes, prod, ["build"])
        self.assertIn("spec", ga["build"])
        self.assertIn("branch", ga["review"])  # build produces branch on the only path


class TestAnalyzeFlow(unittest.TestCase):
    def test_well_formed_flow_is_ok(self):
        owner, routes = load_flow(CONTRACT_METAS)
        a = analyze_flow(owner, routes, CONTRACT_METAS)
        self.assertTrue(a["ok"])
        self.assertEqual(a["entries"], ["build"])
        self.assertIn("ready-merge", a["terminals"])
        self.assertEqual(a["missing"], {})
        self.assertEqual(a["dups"], [])

    def test_broken_composition_flagged(self):
        metas = {k: dict(v) for k, v in CONTRACT_METAS.items()}
        metas["reviewer"] = dict(metas["reviewer"],
                                 accepts={"spec": "required", "design": "required"})
        owner, routes = load_flow(metas)
        a = analyze_flow(owner, routes, metas)
        self.assertFalse(a["ok"])
        self.assertIn("design", a["missing"].get("review", []))

    def test_duplicate_step_owner_flagged(self):
        metas = dict(CONTRACT_METAS)
        metas["coder2"] = {"step": "build"}
        owner, routes = load_flow(metas)
        a = analyze_flow(owner, routes, metas)
        self.assertFalse(a["ok"])
        self.assertTrue(any("build" in d for d in a["dups"]))


if __name__ == "__main__":
    unittest.main()
