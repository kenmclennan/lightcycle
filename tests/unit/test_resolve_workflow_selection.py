import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.resolve_workflow_selection import (
    ResolveWorkflowSelectionInput,
    ResolveWorkflowSelectionUseCase,
)
from tests.support.fake_store import FakeStore


class _StubFlow:
    def __init__(self, pin=None, resolve_error=None, load_error=None):
        self._pin = pin
        self._resolve_error = resolve_error
        self._load_error = load_error
        self.resolve_calls = []
        self.load_calls = []

    def resolve_selection(self, selector):
        self.resolve_calls.append(selector)
        if self._resolve_error:
            raise self._resolve_error
        return self._pin

    def load_graph(self, pin):
        self.load_calls.append(pin)
        if self._load_error:
            raise self._load_error


class TestResolveWorkflowSelection(unittest.TestCase):
    def test_item_target_resolves_to_the_pin_flow_returns(self):
        flow = _StubFlow(pin="lightcycle/solo@abc123")
        resp = ResolveWorkflowSelectionUseCase(flow, FakeStore()).execute(
            ResolveWorkflowSelectionInput(
                node_id="item-1", node_type="item", selector="lightcycle/solo")
        )
        self.assertEqual(resp.value, "lightcycle/solo@abc123")
        self.assertTrue(resp.resolved)
        self.assertEqual(flow.resolve_calls, ["lightcycle/solo"])
        self.assertEqual(flow.load_calls, ["lightcycle/solo@abc123"])

    def test_step_target_resolves_the_same_as_an_item(self):
        flow = _StubFlow(pin="lightcycle/solo@abc123")
        resp = ResolveWorkflowSelectionUseCase(flow, FakeStore()).execute(
            ResolveWorkflowSelectionInput(
                node_id="item-1", node_type="step", selector="lightcycle/solo")
        )
        self.assertTrue(resp.resolved)
        self.assertEqual(resp.value, "lightcycle/solo@abc123")

    def test_an_unresolvable_selector_raises_a_use_case_error_not_the_bare_value_error(self):
        flow = _StubFlow(resolve_error=ValueError("origin 'ghost' has no pulled version"))
        with self.assertRaises(UseCaseError) as ctx:
            ResolveWorkflowSelectionUseCase(flow, FakeStore()).execute(
                ResolveWorkflowSelectionInput(
                    node_id="item-1", node_type="item", selector="ghost/whatever")
            )
        self.assertIn("ghost", str(ctx.exception))

    def test_a_pin_that_fails_to_load_raises_a_use_case_error(self):
        flow = _StubFlow(pin="lightcycle/does-not-exist@abc123",
                          load_error=ValueError("workflow not found"))
        with self.assertRaises(UseCaseError):
            ResolveWorkflowSelectionUseCase(flow, FakeStore()).execute(
                ResolveWorkflowSelectionInput(
                    node_id="item-1", node_type="item", selector="lightcycle/does-not-exist")
            )
