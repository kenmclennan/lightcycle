import unittest

from lightcycle.config import ConfigError
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
    def __init__(self, default_workflow=None):
        self._dw = default_workflow

    def default_origin(self):
        return "lightcycle"

    def default_workflow(self):
        if not self._dw:
            raise ConfigError("default-workflow")
        return self._dw


def _ref_svc(names, default_workflow=None):
    return FlowService(
        FakeFs(METAS), FakeStore(),
        config=_RefCfg(default_workflow), workflow_source=_WFSource(names),
    )


class TestDefaultPinMultiWorkflow(unittest.TestCase):
    def test_single_workflow_is_inferred(self):
        self.assertEqual(_ref_svc(["spec-driven"])._default_pin(), "lightcycle/spec-driven@abc")

    def test_multi_workflow_resolves_the_configured_default(self):
        self.assertEqual(
            _ref_svc(["spec-driven", "bdd-driven"], "lightcycle/spec-driven")._default_pin(),
            "lightcycle/spec-driven@abc",
        )

    def test_multi_workflow_without_a_default_raises_specifically(self):
        with self.assertRaises(ValueError) as ctx:
            _ref_svc(["spec-driven", "bdd-driven"])._default_pin()
        msg = str(ctx.exception)
        self.assertIn("2 workflows", msg)
        self.assertIn("default-workflow", msg)

    def test_default_workflow_naming_an_absent_workflow_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _ref_svc(["spec-driven", "bdd-driven"], "lightcycle/nope")._default_pin()
        self.assertIn("nope", str(ctx.exception))

    def test_present_but_empty_default_workflow_raises_the_clean_error_not_configerror(self):
        with self.assertRaises(ValueError) as ctx:
            _ref_svc(["spec-driven", "bdd-driven"], "")._default_pin()
        self.assertIn("default-workflow", str(ctx.exception))


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
