import unittest

from lightcycle.adapters.tui.design_system import (
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    DONE_GLYPH,
    HUMAN_STEP_GLYPH,
    STATE_GLYPHS,
)
from lightcycle.adapters.tui.hub import hierarchy_row_cells
from lightcycle.adapters.tui.row_grid import GridLayout
from lightcycle.domain.work import HierarchyRow
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step

FLOW = flow_from_metas(
    {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}
)

_NOW = "2026-01-01T00:00:00"

_STACKED_LAYOUT = GridLayout(
    atomic_widths={"id": 10, "turns": 10, "time": 10},
    flexible_width=40,
    stacked=True,
    floor=False,
    floor_width=40,
)


class FixedFlowService:
    def __init__(self, flow, display=None, phase=None):
        self._flow = flow
        self._display = display
        self._phase = phase

    def flow_for(self, node):
        return self._flow

    def display_for(self, node):
        return self._display

    def phase_for(self, node):
        return self._phase


class TestUnstackedShape(unittest.TestCase):
    def test_returns_a_six_tuple_keyed_by_node_id(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        row = HierarchyRow(store.get_node(step), 0)

        cells = hierarchy_row_cells(row, store=store, now=_NOW)

        self.assertEqual(len(cells), 6)
        self.assertEqual(cells[1], step)


class TestGlyphSelectionPerBucket(unittest.TestCase):
    def _glyph_for(self, store, node):
        row = HierarchyRow(node, 0)
        icon_cell, *_ = hierarchy_row_cells(
            row, flow_service=FixedFlowService(FLOW), store=store, now=_NOW,
        )
        return icon_cell

    def test_queued_agent_step(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        icon_cell = self._glyph_for(store, store.get_node(step))
        self.assertEqual(icon_cell.plain, STATE_GLYPHS["queued"].glyph)

    def test_active_agent_step(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        store.claim_ready("agent")
        icon_cell = self._glyph_for(store, store.get_node(step))
        self.assertEqual(icon_cell.plain, STATE_GLYPHS["active"].glyph)

    def test_done_agent_step(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        store.complete_node(step, "done")
        icon_cell = self._glyph_for(store, store.get_node(step))
        self.assertEqual(icon_cell.plain, DONE_GLYPH.glyph)

    def test_gate_human_step_unknown_to_the_flow(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="await-merge", role="human")
        icon_cell = self._glyph_for(store, store.get_node(step))
        self.assertEqual(icon_cell.plain, STATE_GLYPHS["gate"].glyph)

    def test_escalation_human_owned_step_the_flow_still_owns_by_an_agent(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="human")
        icon_cell = self._glyph_for(store, store.get_node(step))
        self.assertEqual(icon_cell.plain, STATE_GLYPHS["escalation"].glyph)

    def test_done_human_step_uses_the_human_glyph_not_the_done_glyph(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="await-merge", role="human")
        store.complete_node(step, "merged")
        icon_cell = self._glyph_for(store, store.get_node(step))
        self.assertEqual(icon_cell.plain, HUMAN_STEP_GLYPH.glyph)


class TestDependencyBlockedExtraGlyph(unittest.TestCase):
    def test_a_blocked_step_gets_the_extra_glyph_appended(self):
        store = FakeStore()
        blocker = create_owned_step(store, "b", step="build", role="agent")
        step = create_owned_step(store, "s", step="build", role="agent", deps=[blocker])
        row = HierarchyRow(store.get_node(step), 0)

        icon_cell, *_ = hierarchy_row_cells(
            row, flow_service=FixedFlowService(FLOW), store=store, now=_NOW,
        )

        self.assertTrue(icon_cell.plain.endswith(DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph))

    def test_an_unblocked_step_has_no_extra_glyph(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        row = HierarchyRow(store.get_node(step), 0)

        icon_cell, *_ = hierarchy_row_cells(
            row, flow_service=FixedFlowService(FLOW), store=store, now=_NOW,
        )

        self.assertNotIn(DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph, icon_cell.plain)


class TestActiveFrameOverride(unittest.TestCase):
    def test_overrides_the_glyph_for_an_active_node(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        store.claim_ready("agent")
        row = HierarchyRow(store.get_node(step), 0)

        icon_cell, *_ = hierarchy_row_cells(
            row, active_frame="◐", flow_service=FixedFlowService(FLOW), store=store, now=_NOW,
        )

        self.assertEqual(icon_cell.plain, "◐")

    def test_leaves_a_queued_node_untouched(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        row = HierarchyRow(store.get_node(step), 0)

        icon_cell, *_ = hierarchy_row_cells(
            row, active_frame="◐", flow_service=FixedFlowService(FLOW), store=store, now=_NOW,
        )

        self.assertEqual(icon_cell.plain, STATE_GLYPHS["queued"].glyph)

    def test_leaves_a_done_node_untouched(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        store.complete_node(step, "done")
        row = HierarchyRow(store.get_node(step), 0)

        icon_cell, *_ = hierarchy_row_cells(
            row, active_frame="◐", flow_service=FixedFlowService(FLOW), store=store, now=_NOW,
        )

        self.assertEqual(icon_cell.plain, DONE_GLYPH.glyph)


class TestLabelComposition(unittest.TestCase):
    def test_an_item_label_is_its_title_regardless_of_flow_service(self):
        store = FakeStore()
        item = store.create_item("The Item Title", "a description")
        row = HierarchyRow(store.get_node(item), 0)

        _, _, title_cell, *_ = hierarchy_row_cells(
            row, flow_service=FixedFlowService(FLOW, display="ignored", phase="ignored"),
        )

        self.assertEqual(title_cell, "The Item Title")

    def test_a_step_with_no_flow_service_falls_back_to_its_stage_verbatim(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        row = HierarchyRow(store.get_node(step), 0)

        _, _, title_cell, *_ = hierarchy_row_cells(row, store=store, now=_NOW)

        self.assertEqual(title_cell, "build")

    def test_a_step_with_a_flow_service_phase_joins_phase_and_display(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        row = HierarchyRow(store.get_node(step), 0)

        _, _, title_cell, *_ = hierarchy_row_cells(
            row, flow_service=FixedFlowService(FLOW, display="Building", phase="Code"),
            store=store, now=_NOW,
        )

        self.assertEqual(title_cell, "Code · Building")

    def test_multi_pass_prefixes_the_pass_number(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        row = HierarchyRow(store.get_node(step), 0)

        _, _, title_cell, *_ = hierarchy_row_cells(
            row,
            flow_service=FixedFlowService(FLOW, display="Building", phase="Code"),
            multi_pass=True,
            store=store, now=_NOW,
        )

        self.assertEqual(title_cell, "pass 1 · Code · Building")


class TestRowDepthIndentation(unittest.TestCase):
    def test_depth_zero_has_no_indent(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        row = HierarchyRow(store.get_node(step), 0)

        _, _, title_cell, *_ = hierarchy_row_cells(row, store=store, now=_NOW)

        self.assertEqual(title_cell, "build")

    def test_depth_one_is_indented_two_spaces(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        row = HierarchyRow(store.get_node(step), 1)

        _, _, title_cell, *_ = hierarchy_row_cells(row, store=store, now=_NOW)

        self.assertEqual(title_cell, "  build")


class TestTurnsCostTimeWiring(unittest.TestCase):
    def test_an_agent_step_with_recorded_usage_has_non_empty_turns_cost_and_time_cells(self):
        clock = {"now": "2026-01-01T10:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        step = create_owned_step(store, "s", step="build", role="agent")
        store.claim_ready("agent")
        store.accrue_active_seconds([step], 600)
        store.record_usage(step, 100, 10, 0, 0, 2.50, "list", None)
        store.record_attribution(step, 50, {})
        row = HierarchyRow(store.get_node(step), 0)

        now = "2026-01-01T10:17:00"
        _, _, _, turns_cell, time_cell, cost_cell = hierarchy_row_cells(row, store=store, now=now)

        self.assertEqual(turns_cell.plain, "50 turns")
        self.assertEqual(cost_cell.plain, "$2.50")
        self.assertEqual(time_cell.plain, "17m (10m active)")

    def test_an_agent_step_that_never_ran_has_empty_turns_cost_and_time_cells(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        row = HierarchyRow(store.get_node(step), 0)

        _, _, _, turns_cell, time_cell, cost_cell = hierarchy_row_cells(
            row, store=store, now=_NOW,
        )

        self.assertEqual(turns_cell, "")
        self.assertEqual(time_cell, "")
        self.assertEqual(cost_cell, "")

    def test_an_item_node_has_empty_turns_cost_and_time_cells(self):
        store = FakeStore()
        item = store.create_item("item", "a description")
        row = HierarchyRow(store.get_node(item), 0)

        _, _, _, turns_cell, time_cell, cost_cell = hierarchy_row_cells(
            row, store=store, now=_NOW,
        )

        self.assertEqual(turns_cell, "")
        self.assertEqual(time_cell, "")
        self.assertEqual(cost_cell, "")

    def test_a_human_step_time_cell_resolves_from_wait_start_not_wall_and_active(self):
        clock = {"now": "2026-01-01T09:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        step = create_owned_step(store, "await-merge", step="await-merge", role="human")
        row = HierarchyRow(store.get_node(step), 0)

        now = "2026-01-01T09:12:00"
        _, _, _, _, time_cell, _ = hierarchy_row_cells(
            row, flow_service=FixedFlowService(FLOW), store=store, now=now,
        )

        self.assertEqual(time_cell.plain, "12m")

    def test_a_non_human_step_time_cell_resolves_wall_and_active(self):
        clock = {"now": "2026-01-01T10:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        step = create_owned_step(store, "building", step="build", role="agent")
        store.claim_ready("agent")
        store.accrue_active_seconds([step], 600)
        row = HierarchyRow(store.get_node(step), 0)

        now = "2026-01-01T10:17:00"
        _, _, _, _, time_cell, _ = hierarchy_row_cells(row, store=store, now=now)

        self.assertEqual(time_cell.plain, "17m (10m active)")


class TestStackedShape(unittest.TestCase):
    def test_returns_a_one_tuple_containing_the_stacked_cell(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        row = HierarchyRow(store.get_node(step), 0)

        cells = hierarchy_row_cells(
            row, layout=_STACKED_LAYOUT, row_budget=60, store=store, now=_NOW,
        )

        self.assertEqual(len(cells), 1)

    def test_the_stacked_cells_content_includes_the_composed_label(self):
        store = FakeStore()
        step = create_owned_step(store, "s", step="build", role="agent")
        row = HierarchyRow(store.get_node(step), 0)

        cells = hierarchy_row_cells(
            row,
            layout=_STACKED_LAYOUT,
            row_budget=60,
            flow_service=FixedFlowService(FLOW, display="Building", phase="Code"),
            store=store,
            now=_NOW,
        )

        self.assertIn("Code · Building", cells[0].plain)


if __name__ == "__main__":
    unittest.main()
