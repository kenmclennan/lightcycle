import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.peek_step import PeekStepInput, PeekStepUseCase
from lightcycle.ports.workflow_bundle import StepPrompt
from tests.support.fake_store import FakeStore


class _FakeFlow:
    def __init__(self, pin=None, resolved=None, error=None, files=None):
        self._pin = pin
        self._resolved = resolved
        self._error = error
        self._files = files or {}

    def workflow_for(self, node):
        return self._pin

    def resolve_selection(self, selector):
        if self._error is not None:
            raise self._error
        return self._resolved

    def file_for_step(self, stage, name=None):
        return self._files.get(stage, stage)


class _FakeWorkflowSource:
    def __init__(self, result=None):
        self._result = result
        self.calls = []

    def resolve_agent(self, role, pin):
        self.calls.append((role, pin))
        return self._result


class TestPeekStepUseCase(unittest.TestCase):
    def test_no_workflow_pin_in_ancestry_raises(self):
        store = FakeStore()
        item = store.create_item("an item", "a description")
        flow = _FakeFlow(pin=None)
        with self.assertRaises(UseCaseError):
            PeekStepUseCase(store, flow, workflow_source=None).execute(
                PeekStepInput(node_id=item, stage="write-code"))

    def test_stage_absent_from_resolved_bundle_raises(self):
        store = FakeStore()
        item = store.create_item("an item", "a description", workflow="acme/build@sha-old")
        flow = _FakeFlow(pin="acme/build@sha-old", resolved="acme/build@sha-new")
        workflow_source = _FakeWorkflowSource(result=None)
        with self.assertRaises(UseCaseError):
            PeekStepUseCase(store, flow, workflow_source=workflow_source).execute(
                PeekStepInput(node_id=item, stage="ghost-stage"))

    def test_resolve_selection_valueerror_is_wrapped_as_usecase_error(self):
        store = FakeStore()
        item = store.create_item("an item", "a description", workflow="acme/build@sha-old")
        flow = _FakeFlow(
            pin="acme/build@sha-old",
            error=ValueError("origin 'acme' has no pulled version; run `lc workflow add`/`upgrade`"),
        )
        with self.assertRaises(UseCaseError):
            PeekStepUseCase(store, flow, workflow_source=None).execute(
                PeekStepInput(node_id=item, stage="write-code"))

    def test_happy_path_returns_fresh_pin_and_body(self):
        store = FakeStore()
        item = store.create_item("an item", "a description", workflow="acme/build@sha-old")
        flow = _FakeFlow(pin="acme/build@sha-old", resolved="acme/build@sha-new")
        workflow_source = _FakeWorkflowSource(
            result=StepPrompt(meta={}, body="step body text"))
        resp = PeekStepUseCase(store, flow, workflow_source=workflow_source).execute(
            PeekStepInput(node_id=item, stage="write-code"))
        self.assertEqual(resp.pin, "acme/build@sha-new")
        self.assertEqual(resp.body, "step body text")

    def test_the_stage_is_resolved_to_its_step_file_before_the_bundle_is_read(self):
        store = FakeStore()
        item = store.create_item("an item", "a description", workflow="acme/build@sha-old")
        flow = _FakeFlow(
            pin="acme/build@sha-old", resolved="acme/build@sha-new",
            files={"write-code": "coder"},
        )
        workflow_source = _FakeWorkflowSource(result=StepPrompt(meta={}, body="b"))
        PeekStepUseCase(store, flow, workflow_source=workflow_source).execute(
            PeekStepInput(node_id=item, stage="write-code"))
        self.assertEqual(workflow_source.calls[0][0], "coder")


if __name__ == "__main__":
    unittest.main()
