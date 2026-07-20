import unittest

from lightcycle.application.flow.flow_check import FlowCheckInput, FlowCheckUseCase
from lightcycle.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore

METAS = {
    "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
    "reviewer": {
        "model": "opus",
        "step": "review",
        "routes": {"done": "open-pr", "rejected": "build"},
    },
}


def svc(store=None):
    return FlowService(FakeFs(METAS), store or FakeStore())


class _WFSource:
    def __init__(self, names, sha="abc"):
        self._names = names
        self._sha = sha

    def current_sha(self, origin):
        return self._sha

    def workflow_names(self, origin, sha):
        return list(self._names)

    def bundle_path(self, origin, sha):
        return "/bundle"


class _RefCfg:
    def default_origin(self):
        return "lightcycle"


def _ref_svc(names):
    return FlowService(
        FakeFs(METAS), FakeStore(), config=_RefCfg(), workflow_source=_WFSource(names),
    )


class TestWorkflowMeta(unittest.TestCase):
    def test_reads_summary_and_when_to_use_frontmatter(self):
        fs = FakeFs(METAS, workflow="---\nsummary: spec to merged\nwhen-to-use: default flow\n---\nentry: build\n")
        svc = FlowService(fs, FakeStore())
        self.assertEqual(
            svc.workflow_meta(),
            {"summary": "spec to merged", "when-to-use": "default flow"},
        )

    def test_no_frontmatter_is_empty(self):
        svc = FlowService(FakeFs(METAS, workflow="entry: build\n"), FakeStore())
        self.assertEqual(svc.workflow_meta(), {})


class TestDefaultPin(unittest.TestCase):
    def test_single_workflow_infers_a_pin(self):
        self.assertEqual(_ref_svc(["spec-driven"])._default_pin(), "lightcycle/spec-driven@abc")

    def test_multiple_workflows_yield_no_default_pin_rather_than_raising(self):
        self.assertIsNone(_ref_svc(["spec-driven", "bdd-driven"])._default_pin())


class TestNodeHelpersTolerateWorkflowLessNodes(unittest.TestCase):
    def _svc_node(self):
        store = FakeStore()
        step = store.create_step("audit: x", step="audit", role="audit")
        svc = FlowService(FakeFs({}), store, config=_RefCfg(), workflow_source=_WFSource(["a", "b"]))
        return svc, store.get_node(step)

    def test_flow_for_a_service_step_is_empty_and_never_reaches_default_pin(self):
        svc, node = self._svc_node()
        self.assertEqual(svc.flow_for(node).steps(), [])

    def test_phase_for_a_service_step_is_none_without_a_crash(self):
        svc, node = self._svc_node()
        self.assertIsNone(svc.phase_for(node))
        svc.workspace_for_node(node)


class TestStepSkill(unittest.TestCase):
    def _svc_store(self):
        metas = {"reviewer": {"model": "opus", "step": "review"}, "gate": {"step": "gate"}}
        wf = "entry: gate\n\nedges:\n  gate  done  review\n\nnodes:\n  review  reviewer\n"
        store = FakeStore()
        svc = FlowService(
            FakeFs(metas, workflow=wf, bodies={"gate": "GATE SKILL BODY", "reviewer": "REVIEWER BODY"}),
            store,
        )
        return svc, store

    def test_human_gate_step_returns_its_skill_body(self):
        svc, store = self._svc_store()
        item = store.create_item("i", theme=store.create_theme("t"), workflow="wf")
        step = store.create_step("gate: i", step="gate", role="human", parent=item)
        self.assertEqual(svc.step_skill(store.get_node(step)), "GATE SKILL BODY")

    def test_agent_step_has_no_skill(self):
        svc, store = self._svc_store()
        item = store.create_item("i", theme=store.create_theme("t"), workflow="wf")
        step = store.create_step("review: i", step="review", role="reviewer", parent=item)
        self.assertIsNone(svc.step_skill(store.get_node(step)))

    def test_workflow_less_node_has_no_skill(self):
        svc, store = self._svc_store()
        item = store.create_item("i", theme=store.create_theme("t"))
        step = store.create_step("gate: i", step="gate", role="human", parent=item)
        self.assertIsNone(svc.step_skill(store.get_node(step)))


class TestFlowCheckSelectsWorkflow(unittest.TestCase):
    def _svc(self):
        wfs = {
            "wf-a": "entry: coder\n\nedges:\n  coder  done  reviewer\n",
            "wf-b": "entry: reviewer\n\nedges:\n  reviewer  done  open-pr\n",
        }
        return FlowService(FakeFs(METAS, workflow=wfs), FakeStore())

    def test_named_workflow_is_loaded(self):
        a = FlowCheckUseCase(self._svc()).execute(FlowCheckInput(workflow="wf-a"))
        b = FlowCheckUseCase(self._svc()).execute(FlowCheckInput(workflow="wf-b"))
        self.assertIn("coder", a.analysis["steps"])
        self.assertNotIn("coder", b.analysis["steps"])


class TestFlowService(unittest.TestCase):
    def test_role_metas(self):
        self.assertEqual(svc().role_metas(), METAS)

    def test_load_flow_returns_assembled_flow(self):
        flow = svc().load_flow()
        self.assertEqual(flow.owner_of("build"), "coder")
        self.assertEqual(flow.owner_of("review"), "reviewer")
        self.assertEqual(flow.next("build", "done").to_step, "review")

    def test_flow_next_derives_owner_of_target(self):
        t = svc().flow_next("build", "done")
        self.assertEqual((t.to_step, t.to_role), ("review", "reviewer"))
        t2 = svc().flow_next("review", "rejected")
        self.assertEqual((t2.to_step, t2.to_role), ("build", "coder"))

    def test_flow_next_unknown_outcome_is_none(self):
        self.assertIsNone(svc().flow_next("build", "nope"))

    def test_meta_for_step_returns_owning_role_meta(self):
        self.assertEqual(svc().meta_for_step("build"), METAS["coder"])

    def test_meta_for_step_unowned_is_empty(self):
        self.assertEqual(svc().meta_for_step("ready-merge"), {})

    def test_meta_for_step_resolves_bare_human_step_by_file_not_role(self):
        metas = {
            "review-plan": {
                "step": "review-plan",
                "accepts": {"spec": "required"},
                "routes": {"approved": "build"},
            },
            "coder": {"model": "sonnet", "step": "build"},
        }
        fs = FakeFs(metas, workflow=graph_text_from_metas(metas, entry="review-plan"))
        service = FlowService(fs, FakeStore())
        self.assertEqual(service.load_flow().owner_of("review-plan"), "human")
        self.assertEqual(service.meta_for_step("review-plan"), metas["review-plan"])

    def test_ready_roles_from_store(self):
        store = FakeStore()
        store.create_step("b", step="build", role="coder")
        self.assertIn("coder", svc(store).ready_roles())


class TestPhaseFor(unittest.TestCase):
    def _step(self, metas):
        store = FakeStore()
        item = store.create_item("st", theme=store.create_theme("theme"), workflow="w")
        step = store.get_node(store.create_step("b", step="build", role="coder", parent=item))
        return FlowService(FakeFs(metas, workflow=graph_text_from_metas(metas)), store), step

    def test_returns_the_steps_declared_phase(self):
        service, step = self._step(
            {"coder": {"model": "sonnet", "step": "build", "phase": "code"}})
        self.assertEqual(service.phase_for(step), "code")

    def test_is_none_when_the_step_declares_no_phase(self):
        service, step = self._step({"coder": {"model": "sonnet", "step": "build"}})
        self.assertIsNone(service.phase_for(step))


if __name__ == "__main__":
    unittest.main()
