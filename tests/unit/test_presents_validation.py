import unittest
from types import SimpleNamespace

from lightcycle.application.workflows.bundle_check import check_bundle_references

WORKFLOW = """# Flow

entry: build

edges:
  build  done  gate
"""

AGENT = "---\nmodel: sonnet\n%s---\n# Build\n"
GATE = "---\npresents: %s\n---\n# Gate\n"


def problems_for(gate_presents, build_front=""):
    steps = {"build": AGENT % build_front, "gate": GATE % gate_presents}
    bundle = SimpleNamespace(steps=steps, workflows={"flow": WORKFLOW})
    return [m for ms in check_bundle_references(bundle).values() for m in ms if "presents" in m]


class TestPresentsValidation(unittest.TestCase):
    def test_an_unknown_value_names_the_step(self):
        found = problems_for("tab:log")
        self.assertEqual(len(found), 1)
        self.assertIn("'gate'", found[0])
        self.assertIn("tab:log", found[0])

    def test_an_artifact_no_step_produces_names_the_step(self):
        found = problems_for("artifact:findings")
        self.assertEqual(len(found), 1)
        self.assertIn("'gate'", found[0])
        self.assertIn("no step in the workflow produces", found[0])

    def test_the_same_bundle_passes_once_a_step_produces_the_artifact(self):
        self.assertEqual(
            problems_for("artifact:findings", build_front="produces:\n  findings: optional\n"), [])

    def test_pr_and_description_pass(self):
        self.assertEqual(problems_for("pr"), [])
        self.assertEqual(problems_for("description"), [])

    def test_presents_on_a_non_human_step_names_the_step(self):
        steps = {"build": "---\nmodel: sonnet\npresents: pr\n---\n# Build\n", "gate": "# Gate\n"}
        bundle = SimpleNamespace(steps=steps, workflows={"flow": WORKFLOW})

        found = [m for ms in check_bundle_references(bundle).values() for m in ms if "presents" in m]

        self.assertEqual(len(found), 1)
        self.assertIn("'build'", found[0])
        self.assertIn("only for human steps", found[0])
