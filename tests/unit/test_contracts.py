import unittest
from pathlib import Path

from the_grid.adapters.fsio import parse_step, step_roles
from the_grid.domain.contracts import ArtifactRequirement, FlowContracts, StepContract
from the_grid.domain.flow import Flow

_ROOT = str(Path(__file__).resolve().parents[2])

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
    return FlowContracts(Flow.assemble(metas), metas)


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

    def test_duplicate_step_owner_flagged(self):
        metas = dict(CONTRACT_METAS)
        metas["coder2"] = {"step": "build"}
        a = contracts(metas)
        self.assertFalse(a.ok())
        self.assertTrue(any("build" in d for d in a.duplicates()))


class TestRealStepsFlowComposition(unittest.TestCase):
    def test_real_steps_flow_is_ok(self):
        role_metas = {
            role: (parse_step(_ROOT, role) or {"meta": {}})["meta"]
            for role in step_roles(_ROOT)
        }
        flow = Flow.assemble(role_metas)
        result = FlowContracts(flow, role_metas).as_dict()
        self.assertTrue(result["ok"],
                        msg="Flow composition error - missing inputs: %s" % result.get("missing", {}))


if __name__ == "__main__":
    unittest.main()
