import unittest
from pathlib import Path

from lightcycle.adapters.fsio import parse_step, step_roles, workflow_text
from lightcycle.domain.contracts import ArtifactRequirement, FlowContracts, StepContract
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from tests.support.fake_fs import graph_text_from_metas

_ROOT = str(Path(__file__).resolve().parents[2] / "lightcycle" / "library")

CONTRACT_METAS = {
    "coder": {
        "step": "build",
        "accepts": {"spec": "required", "branch": "optional"},
        "produces": {"branch": "required"},
        "routes": {"done": "review"},
    },
    "reviewer": {
        "step": "review",
        "accepts": {"spec": "required", "branch": "required"},
        "routes": {"done": "open-pr", "rejected": "build"},
    },
    "pr-watcher": {
        "step": "open-pr",
        "accepts": {"branch": "required"},
        "produces": {"pr": "required"},
        "routes": {"done": "ready-merge", "ci-failed": "build"},
    },
}


def contracts(metas):
    graph = parse_graph(graph_text_from_metas(metas))
    return FlowContracts(Flow.from_graph(graph, metas), graph, metas)


class TestArtifactRequirement(unittest.TestCase):
    def test_from_block_required_is_the_default(self):
        reqs = ArtifactRequirement.from_block({"spec": "required", "branch": "optional"})
        self.assertEqual({(r.type, r.required) for r in reqs}, {("spec", True), ("branch", False)})

    def test_non_dict_block_is_empty(self):
        self.assertEqual(ArtifactRequirement.from_block(None), [])


class TestStepContract(unittest.TestCase):
    def test_required_optional_split(self):
        c = StepContract.from_meta({"accepts": {"spec": "required", "branch": "optional"}})
        self.assertEqual(c.required_inputs(), {"spec"})
        self.assertEqual(c.optional_inputs(), {"branch"})

    def test_produces(self):
        c = StepContract.from_meta({"produces": {"branch": "required"}})
        self.assertEqual(c.required_outputs(), {"branch"})

    def test_no_block_is_empty(self):
        self.assertEqual(StepContract.from_meta({}).required_inputs(), set())

    def test_missing_inputs(self):
        c = StepContract.from_meta({"accepts": {"spec": "required", "branch": "required"}})
        self.assertEqual(c.missing_inputs({"spec"}), {"branch"})

    def test_missing_outputs_required_by_target(self):
        c = StepContract.from_meta({"produces": {"pr": "required"}})
        target = StepContract.from_meta({"accepts": {"pr": "required"}})
        self.assertEqual(c.missing_outputs(set(), target), {"pr"})
        self.assertEqual(c.missing_outputs({"pr"}, target), set())

    def test_missing_outputs_no_target_demands_nothing(self):
        c = StepContract.from_meta({"produces": {"pr": "required"}})
        self.assertEqual(c.missing_outputs(set(), None), set())

    def test_missing_outputs_target_not_requiring_demands_nothing(self):
        c = StepContract.from_meta({"produces": {"pr": "required"}})
        target = StepContract.from_meta({})
        self.assertEqual(c.missing_outputs(set(), target), set())


class TestFlowContracts(unittest.TestCase):
    def test_well_formed_flow_is_ok(self):
        a = contracts(CONTRACT_METAS)
        self.assertTrue(a.ok())
        self.assertEqual(a.entries(), ["build"])
        self.assertIn("ready-merge", a.terminals())
        self.assertEqual(a.missing(), {})
        self.assertEqual(a.duplicates(), [])

    def test_entry_guarantee_satisfies_downstream_required_input(self):
        a = contracts(CONTRACT_METAS)
        d = a.as_dict()
        self.assertIn("spec", d["req"]["build"])
        self.assertEqual(d["missing"], {})

    def test_broken_composition_flagged(self):
        metas = {k: dict(v) for k, v in CONTRACT_METAS.items()}
        metas["reviewer"] = dict(
            metas["reviewer"], accepts={"spec": "required", "design": "required"}
        )
        a = contracts(metas)
        self.assertFalse(a.ok())
        self.assertIn("design", a.missing().get("review", []))

class TestUnresolvedSteps(unittest.TestCase):
    def test_destination_only_fileless_target_is_not_unresolved(self):
        metas = {"coder": {"step": "build", "routes": {"done": "review-conflict"}}}
        graph = parse_graph(graph_text_from_metas(metas))
        flow = Flow.from_graph(graph, metas)
        self.assertEqual(FlowContracts(flow, graph, metas).unresolved_steps(), [])

    def test_entry_without_a_step_file_is_unresolved(self):
        graph = parse_graph("entry: missing\n")
        flow = Flow.from_graph(graph, {})
        self.assertEqual(FlowContracts(flow, graph, {}).unresolved_steps(), ["missing"])

    def test_edge_source_without_a_step_file_is_unresolved(self):
        text = "entry: build\n\nedges:\n  build  done  next\n  next  done  build\n"
        graph = parse_graph(text)
        metas = {"build": {"step": "build", "model": "x"}}
        flow = Flow.from_graph(graph, metas)
        self.assertEqual(FlowContracts(flow, graph, metas).unresolved_steps(), ["next"])


class TestRealStepsFlowComposition(unittest.TestCase):
    def _graph_flow(self):
        step_metas = {
            role: (parse_step(_ROOT, role) or {"meta": {}})["meta"]
            for role in step_roles(_ROOT)
        }
        graph = parse_graph(workflow_text(_ROOT, "spec-driven"))
        return graph, Flow.from_graph(graph, step_metas), step_metas

    def test_real_steps_flow_is_ok(self):
        graph, flow, step_metas = self._graph_flow()
        result = FlowContracts(flow, graph, step_metas).as_dict()
        self.assertTrue(result["ok"],
                        msg="Flow composition error - missing inputs: %s" % result.get("missing", {}))

    def test_spec_writer_is_the_entry_and_sources_the_specs_repo(self):
        graph, _, _ = self._graph_flow()
        self.assertEqual(graph.entry, "spec-writer")
        self.assertEqual(graph.requires, {"brief", "repo"})
        self.assertEqual(graph.workspace_for("spec-writer"), "specs")
        self.assertEqual(graph.workspace_for("write-code"), "project")

    def test_spec_phase_reuses_open_pr_and_the_pr_watch(self):
        graph, flow, _ = self._graph_flow()
        self.assertEqual(graph.file_for("spec-open-pr"), "open-pr")
        self.assertEqual(graph.target("spec-open-pr", "done"), "spec-await-merge")
        self.assertEqual(graph.target("spec-await-merge", "changes"), "spec-writer")
        self.assertEqual(flow.merge_outcome("spec-await-merge"), "spec-merged")
        self.assertEqual(flow.close_outcome("spec-await-merge"), "abandoned")
        self.assertEqual(flow.mention_token("spec-await-merge"), "@lc")

    def test_spec_merge_continues_into_the_code_phase(self):
        graph, flow, _ = self._graph_flow()
        self.assertEqual(graph.target("spec-await-merge", "spec-merged"), "write-code")
        self.assertEqual(flow.merge_outcome("code-await-merge"), "merged")

    def test_audit_findings_routes_to_review_findings(self):
        graph, flow, _ = self._graph_flow()
        self.assertEqual(graph.target("audit", "findings"), "review-findings")
        self.assertEqual(flow.owner_of("review-findings"), "human")

    def test_audit_clean_is_terminal(self):
        graph, flow, _ = self._graph_flow()
        self.assertIsNone(flow.next("audit", "clean"))
        self.assertIsNone(graph.target("audit", "clean"))

    def test_spec_writer_step_accepts_brief_and_produces_spec(self):
        meta = (parse_step(_ROOT, "spec-writer") or {"meta": {}})["meta"]
        self.assertEqual(meta.get("accepts"), {"brief": "required"})
        self.assertEqual(meta.get("produces"), {"spec": "required"})

    def test_ci_failed_cap_escalates_to_review_ci_after_three(self):
        graph, flow, _ = self._graph_flow()
        self.assertEqual(flow.ci_failed_cap_n("watch-ci"), 3)
        self.assertEqual(flow.ci_failed_cap_target("watch-ci"), "review-ci")
        self.assertEqual(flow.owner_of("review-ci"), "human")
        self.assertEqual(flow.outcomes_for("review-ci"), [])


if __name__ == "__main__":
    unittest.main()
