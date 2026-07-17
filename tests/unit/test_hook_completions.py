import datetime
import unittest

from lightcycle.application.pool.hook_completions import HookCompletionsUseCase
from lightcycle.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore


def _ts(iso_str):
    return datetime.datetime.fromisoformat(iso_str).timestamp()


def _set_closed_at(store, tid, iso_str):
    store._records[tid]["closed_at"] = iso_str


class TestHookCompletionsNoHookSteps(unittest.TestCase):
    def test_no_hook_steps_returns_empty(self):
        s = FakeStore()
        flow_svc = FlowService(FakeFs({"coder": {"model": "sonnet", "step": "build"}}), s)
        result = HookCompletionsUseCase(s, flow_svc).execute(None)
        self.assertEqual(result.completed, [])


class TestHookCompletionsDetection(unittest.TestCase):
    def test_closed_hook_task_is_reported(self):
        s = FakeStore()
        flow_svc = FlowService(FakeFs({"auditor": {"model": "sonnet", "step": "audit",
                                                     "on_theme_close": True}}), s)
        tid = s.create_step("audit: theme", step="audit", role="auditor")
        s.close(tid, "done")
        _set_closed_at(s, tid, "2026-01-01T12:00:00")
        result = HookCompletionsUseCase(s, flow_svc).execute(None)
        self.assertEqual(result.completed, [("audit", tid, "done")])

    def test_notes_preferred_over_outcome_as_detail(self):
        s = FakeStore()
        flow_svc = FlowService(FakeFs({"auditor": {"model": "sonnet", "step": "audit",
                                                     "on_theme_close": True}}), s)
        tid = s.create_step("audit: theme", step="audit", role="auditor")
        s.note(tid, "no finding")
        s.close(tid, "done")
        _set_closed_at(s, tid, "2026-01-01T12:00:00")
        result = HookCompletionsUseCase(s, flow_svc).execute(None)
        self.assertEqual(result.completed, [("audit", tid, "no finding")])

    def test_non_hook_step_task_not_reported(self):
        s = FakeStore()
        flow_svc = FlowService(FakeFs({"coder": {"model": "sonnet", "step": "build"}}), s)
        tid = s.create_step("build: x", step="build", role="coder")
        s.close(tid, "done")
        result = HookCompletionsUseCase(s, flow_svc).execute(None)
        self.assertEqual(result.completed, [])

    def test_unclosed_hook_task_not_reported(self):
        s = FakeStore()
        flow_svc = FlowService(FakeFs({"auditor": {"model": "sonnet", "step": "audit",
                                                     "on_theme_close": True}}), s)
        s.create_step("audit: theme", step="audit", role="auditor")
        result = HookCompletionsUseCase(s, flow_svc).execute(None)
        self.assertEqual(result.completed, [])

    def test_arbitrary_hook_name_detected_generically(self):
        s = FakeStore()
        flow_svc = FlowService(FakeFs({"deployer": {"model": "sonnet", "step": "deploy",
                                                      "on_deploy_green": True}}), s)
        tid = s.create_step("deploy: x", step="deploy", role="deployer")
        s.close(tid, "done")
        _set_closed_at(s, tid, "2026-01-01T12:00:00")
        result = HookCompletionsUseCase(s, flow_svc).execute(None)
        self.assertEqual(result.completed, [("deploy", tid, "done")])


class TestHookCompletionsPerItem(unittest.TestCase):
    def _fs(self):
        hooked = {"auditor": {"model": "s", "step": "audit", "on_theme_close": True}}
        plain = {"builder": {"model": "s", "step": "audit"}}
        return FakeFs(hooked, workflows={
            "wfA": graph_text_from_metas(hooked),
            "wfB": graph_text_from_metas(plain),
        })

    def _done_audit(self, s, workflow):
        theme = s.create_theme("t-%s" % workflow)
        item = s.create_item("i-%s" % workflow, theme=theme, workflow=workflow)
        tid = s.create_step("audit: %s" % workflow, step="audit", role="auditor", parent=item)
        s.close(tid, "done")
        _set_closed_at(s, tid, "2026-01-01T12:00:00")
        return tid

    def test_hooks_resolve_per_item_not_from_a_single_default_flow(self):
        s = FakeStore()
        flow_svc = FlowService(self._fs(), s)
        on_a = self._done_audit(s, "wfA")
        self._done_audit(s, "wfB")
        result = HookCompletionsUseCase(s, flow_svc).execute(None)
        self.assertEqual(result.completed, [("audit", on_a, "done")])

    def test_reports_a_non_default_workflow_hook_even_after_its_item_is_done(self):
        s = FakeStore()
        role = {"auditor": {"model": "s", "step": "audit"}}
        hooked = {"auditor": {"model": "s", "step": "audit", "on_theme_close": True}}
        fs = FakeFs(role, workflows={"wfX": graph_text_from_metas(hooked)})
        flow_svc = FlowService(fs, s)
        item = s.create_item("i", theme=s.create_theme("t"), workflow="wfX")
        tid = s.create_step("audit: X", step="audit", role="auditor", parent=item)
        s.close(tid, "done")
        _set_closed_at(s, tid, "2026-01-01T12:00:00")
        s.close(item, "done")
        result = HookCompletionsUseCase(s, flow_svc).execute(None)
        self.assertEqual(result.completed, [("audit", tid, "done")])


class TestHookCompletionsSinceThreshold(unittest.TestCase):
    def test_closed_before_since_is_excluded(self):
        s = FakeStore()
        flow_svc = FlowService(FakeFs({"auditor": {"model": "sonnet", "step": "audit",
                                                     "on_theme_close": True}}), s)
        tid = s.create_step("audit: theme", step="audit", role="auditor")
        s.close(tid, "done")
        _set_closed_at(s, tid, "2026-01-01T12:00:00")
        result = HookCompletionsUseCase(s, flow_svc).execute(_ts("2026-01-02T00:00:00"))
        self.assertEqual(result.completed, [])

    def test_closed_after_since_is_included(self):
        s = FakeStore()
        flow_svc = FlowService(FakeFs({"auditor": {"model": "sonnet", "step": "audit",
                                                     "on_theme_close": True}}), s)
        tid = s.create_step("audit: theme", step="audit", role="auditor")
        s.close(tid, "done")
        _set_closed_at(s, tid, "2026-01-03T00:00:00")
        result = HookCompletionsUseCase(s, flow_svc).execute(_ts("2026-01-02T00:00:00"))
        self.assertEqual(result.completed, [("audit", tid, "done")])

    def test_a_prior_completion_is_not_reported_again_next_tick(self):
        s = FakeStore()
        flow_svc = FlowService(FakeFs({"auditor": {"model": "sonnet", "step": "audit",
                                                     "on_theme_close": True}}), s)
        tid = s.create_step("audit: theme", step="audit", role="auditor")
        s.close(tid, "done")
        _set_closed_at(s, tid, "2026-01-01T12:00:00")
        use_case = HookCompletionsUseCase(s, flow_svc)
        first = use_case.execute(None)
        self.assertEqual(first.completed, [("audit", tid, "done")])
        second = use_case.execute(_ts("2026-01-01T12:00:00"))
        self.assertEqual(second.completed, [])


if __name__ == "__main__":
    unittest.main()
