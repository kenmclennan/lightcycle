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

class TestRealStepsFlowComposition(unittest.TestCase):
    def test_real_steps_flow_is_ok(self):
        step_metas = {
            role: (parse_step(_ROOT, role) or {"meta": {}})["meta"]
            for role in step_roles(_ROOT)
        }
        graph = parse_graph(workflow_text(_ROOT, "standard"))
        flow = Flow.from_graph(graph, step_metas)
        result = FlowContracts(flow, graph, step_metas).as_dict()
        self.assertTrue(result["ok"],
                        msg="Flow composition error - missing inputs: %s" % result.get("missing", {}))

    def test_review_spec_is_the_entry_gate_before_the_coder(self):
        graph = parse_graph(workflow_text(_ROOT, "standard"))
        self.assertEqual(graph.entry, "review-spec")
        self.assertEqual(graph.target("review-spec", "approved"), "write-code")
        self.assertEqual(graph.target("review-spec", "changes"), "draft-spec")

    def test_audit_findings_routes_to_review_findings(self):
        step_metas = {
            role: (parse_step(_ROOT, role) or {"meta": {}})["meta"]
            for role in step_roles(_ROOT)
        }
        graph = parse_graph(workflow_text(_ROOT, "standard"))
        flow = Flow.from_graph(graph, step_metas)
        self.assertEqual(graph.target("audit", "findings"), "review-findings")
        self.assertEqual(flow.owner_of("review-findings"), "human")

    def test_audit_clean_is_terminal(self):
        step_metas = {
            role: (parse_step(_ROOT, role) or {"meta": {}})["meta"]
            for role in step_roles(_ROOT)
        }
        graph = parse_graph(workflow_text(_ROOT, "standard"))
        flow = Flow.from_graph(graph, step_metas)
        self.assertIsNone(flow.next("audit", "clean"))
        self.assertIsNone(graph.target("audit", "clean"))

    def test_spec_workflow_entry_sources_worktrees_from_the_specs_repo(self):
        graph = parse_graph(workflow_text(_ROOT, "spec"))
        self.assertEqual(graph.entry, "spec-writer")
        self.assertEqual(graph.workspace, "specs")
        self.assertEqual(graph.requires, {"brief"})
        self.assertIsNone(graph.target("spec-writer", "done"))

    def test_spec_writer_step_accepts_brief_and_produces_spec(self):
        meta = (parse_step(_ROOT, "spec-writer") or {"meta": {}})["meta"]
        self.assertEqual(meta.get("accepts"), {"brief": "required"})
        self.assertEqual(meta.get("produces"), {"spec": "required"})

    def test_ci_failed_cap_escalates_to_review_ci_after_three(self):
        step_metas = {
            role: (parse_step(_ROOT, role) or {"meta": {}})["meta"]
            for role in step_roles(_ROOT)
        }
        graph = parse_graph(workflow_text(_ROOT, "standard"))
        flow = Flow.from_graph(graph, step_metas)
        self.assertEqual(flow.ci_failed_cap_n("watch-ci"), 3)
        self.assertEqual(flow.ci_failed_cap_target("watch-ci"), "review-ci")
        self.assertEqual(flow.owner_of("review-ci"), "human")
        self.assertEqual(flow.outcomes_for("review-ci"), [])


if __name__ == "__main__":
    unittest.main()
