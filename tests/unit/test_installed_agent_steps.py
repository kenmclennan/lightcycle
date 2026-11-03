import tempfile
import unittest
from pathlib import Path

from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter
from lightcycle.application.services.installed_agent_steps import InstalledAgentSteps
from lightcycle.config import Config
from tests.support.installed_steps import AGENT, HUMAN, SCRIPT, graph, installed

LIBRARY = Path(__file__).resolve().parent.parent / "support" / "library"


class TestInstalledAgentSteps(unittest.TestCase):
    def _list(self, origins):
        source, bundle = installed(origins)
        return InstalledAgentSteps(source, bundle, None).list()

    def test_origin_without_a_current_sha_contributes_nothing(self):
        found = self._list({
            "a": ("s1", {"w": AGENT}, {"wf": graph(("w", "done", "w2"))}),
            "b": (None, {"w": AGENT}, {"wf": graph(("w", "done", "w2"))}),
        })
        self.assertEqual({o for o, _ in found}, {"a"})

    def test_script_and_human_stages_are_excluded(self):
        found = self._list({"a": ("s1", {"w": AGENT, "s": SCRIPT, "h": HUMAN}, {
            "wf": graph(("w", "done", "s"), ("s", "done", "h"))})})
        self.assertEqual(found, [("a", "w")])

    def test_same_stage_in_two_workflows_appears_once(self):
        wf = graph(("w", "done", "h"))
        found = self._list({"a": ("s1", {"w": AGENT, "h": HUMAN}, {"x": wf, "y": wf})})
        self.assertEqual(found, [("a", "w")])

    def test_stage_reachable_only_through_edges_is_included(self):
        found = self._list({"a": ("s1", {"w": AGENT, "h": HUMAN}, {
            "wf": graph(("h", "ok", "w"), entry="h")})})
        self.assertEqual(found, [("a", "w")])

    def test_workflow_whose_graph_does_not_parse_is_skipped(self):
        found = self._list({"a": ("s1", {"w": AGENT}, {
            "bad": "entry: w\n\nworkspace: one two\n",
            "good": graph(("w", "done", "h")),
        })})
        self.assertEqual(found, [("a", "w")])

    def test_committed_spec_driven_bundle(self):
        class Source:
            def list_origins(self):
                return ["lib"]

            def read_registry(self, origin):
                return type("R", (), {"current": "s"})()

            def pinned_bundle(self, origin, sha):
                return str(LIBRARY)

        found = InstalledAgentSteps(Source(), WorkflowBundleAdapter(), None).list()
        stages = {stage for _, stage in found}
        self.assertTrue({"spec-writer", "write-code", "spec-open-pr"} <= stages)
        self.assertNotIn("spec-await-merge", stages)

    def test_agent_step_including_an_engine_fragment_is_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "steps").mkdir()
            (root / "workflows").mkdir()
            (root / "steps" / "w.md").write_text(
                "---\nmodel: sonnet\n---\n\n# W\n\n@include plain-language\n")
            (root / "workflows" / "wf.md").write_text(graph(("w", "done", "h")))

            class Source:
                def list_origins(self):
                    return ["o"]

                def read_registry(self, origin):
                    return type("R", (), {"current": "s"})()

                def pinned_bundle(self, origin, sha):
                    return str(root)

            class Cfg:
                def prompts_root(self):
                    return Config.prompts_root(None)

            bundle = WorkflowBundleAdapter()
            without = InstalledAgentSteps(Source(), bundle, None).list()
            found = InstalledAgentSteps(Source(), bundle, Cfg()).list()
        self.assertEqual(without, [])
        self.assertEqual(found, [("o", "w")])
