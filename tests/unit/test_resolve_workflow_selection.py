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
    def test_theme_target_passes_the_raw_selector_through_unresolved(self):
        flow = _StubFlow()
        resp = ResolveWorkflowSelectionUseCase(flow, FakeStore()).execute(
            ResolveWorkflowSelectionInput(
                node_id="item-1", node_type="theme", selector="lightcycle/solo")
        )
        self.assertEqual(resp.value, "lightcycle/solo")
        self.assertFalse(resp.resolved)
        self.assertEqual(flow.resolve_calls, [])

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


class TestResolveWorkflowSelectionShadowing(unittest.TestCase):
    def test_no_descendants_reports_nothing_shadowed(self):
        store = FakeStore()
        item = store.create_item("item")
        resp = ResolveWorkflowSelectionUseCase(_StubFlow(), store).execute(
            ResolveWorkflowSelectionInput(node_id=item, node_type="theme", selector="x")
        )
        self.assertEqual(resp.shadowed_by, [])

    def test_a_direct_child_with_its_own_pin_is_reported(self):
        store = FakeStore()
        theme = store.create_theme("theme")
        child = store.create_item("child", theme=theme)
        store.edit_node(child, workflow="lightcycle/solo@abc123")
        resp = ResolveWorkflowSelectionUseCase(_StubFlow(), store).execute(
            ResolveWorkflowSelectionInput(node_id=theme, node_type="theme", selector="x")
        )
        self.assertEqual(resp.shadowed_by, [child])

    def test_a_childless_descendant_with_no_pin_is_not_reported(self):
        store = FakeStore()
        theme = store.create_theme("theme")
        store.create_item("child", theme=theme)
        resp = ResolveWorkflowSelectionUseCase(_StubFlow(), store).execute(
            ResolveWorkflowSelectionInput(node_id=theme, node_type="theme", selector="x")
        )
        self.assertEqual(resp.shadowed_by, [])

    def test_recursion_stops_at_the_nearest_shadow_not_the_grandchild_too(self):
        store = FakeStore()
        theme = store.create_theme("theme")
        child = store.create_item("child", theme=theme)
        store.edit_node(child, workflow="lightcycle/solo@abc123")
        grandchild = store.create_step("grandchild", parent=child)
        store.edit_node(grandchild, workflow="lightcycle/solo@def456")
        resp = ResolveWorkflowSelectionUseCase(_StubFlow(), store).execute(
            ResolveWorkflowSelectionInput(node_id=theme, node_type="theme", selector="x")
        )
        self.assertEqual(resp.shadowed_by, [child])

    def test_a_grandchild_pin_surfaces_when_the_child_has_none(self):
        store = FakeStore()
        theme = store.create_theme("theme")
        child = store.create_item("child", theme=theme)
        grandchild = store.create_step("grandchild", parent=child)
        store.edit_node(grandchild, workflow="lightcycle/solo@abc123")
        resp = ResolveWorkflowSelectionUseCase(_StubFlow(), store).execute(
            ResolveWorkflowSelectionInput(node_id=theme, node_type="theme", selector="x")
        )
        self.assertEqual(resp.shadowed_by, [grandchild])

    def test_only_the_shadowing_sibling_is_named_not_both_and_not_neither(self):
        store = FakeStore()
        theme = store.create_theme("theme")
        shadowing = store.create_item("shadowing", theme=theme)
        store.edit_node(shadowing, workflow="lightcycle/solo@abc123")
        store.create_item("plain", theme=theme)
        resp = ResolveWorkflowSelectionUseCase(_StubFlow(), store).execute(
            ResolveWorkflowSelectionInput(node_id=theme, node_type="theme", selector="x")
        )
        self.assertEqual(resp.shadowed_by, [shadowing])


if __name__ == "__main__":
    unittest.main()
