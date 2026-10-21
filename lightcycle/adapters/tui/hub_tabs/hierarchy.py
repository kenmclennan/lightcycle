from lightcycle.adapters.tui.design_system import (
    ACTIVE_GLYPH_FRAMES,
    ACTIVE_GLYPH_REST_INDEX,
    ACTIVE_GLYPH_TICKS_PER_SECOND,
    COLOURS,
    COLUMN_GRIDS,
    next_active_glyph_frame,
)
from lightcycle.adapters.tui.row_grid import (
    GLYPH_WIDTHS,
    apply_widths,
    compute_layout,
    floor_message,
    render_screen_row_budget,
    screen_row_budget_for,
)
from lightcycle.domain.work import row_bucket
from rich.text import Text
from textual.widgets import Static
from textual.widgets.data_table import CellDoesNotExist
from lightcycle.adapters.tui.hub_render import (
    HIERARCHY_CONTINUATION_BASE_INDENT,
    STACKED_COLUMN_KEY,
    _flow_for_bucket,
    hierarchy_row_cells,
    hierarchy_time_text,
    hierarchy_usage_text,
)
from lightcycle.adapters.tui.hub_widgets import HierarchyPagingTable


class HierarchyTabMixin:
    def _hierarchy_layout(self, table, rows):
        store = self._container.store
        now = self._now().isoformat()
        step_rows = [r for r in rows if r.node.type == "step"]
        usage = [hierarchy_usage_text(r.node) for r in step_rows]
        atomic_values = {
            "id": [r.node.id for r in rows],
            "turns": [turns_text for turns_text, _cost_text in usage],
            "time": [hierarchy_time_text(store, r.node, now) for r in step_rows],
            "cost": [cost_text for _turns_text, cost_text in usage],
        }
        row_budget = screen_row_budget_for(table, len(COLUMN_GRIDS["workflow"]))
        max_depth = max((r.depth for r in rows), default=0)
        indent = HIERARCHY_CONTINUATION_BASE_INDENT + max_depth
        return compute_layout(row_budget, ["icon"], atomic_values, indent)

    def refresh_hierarchy_width(self) -> None:
        table = self.query_one(HierarchyPagingTable)
        if not self._last_rows:
            return
        layout = self._hierarchy_layout(table, self._last_rows)
        if layout.floor != self._hierarchy_floor or layout.stacked != self._hierarchy_stacked or layout.stacked:
            self._render_hierarchy(self._last_rows, self._last_multi_pass, initial=True)
            self._apply_tab_visibility()
            return
        if layout.floor:
            self.query_one("#hierarchy-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["workflow"])), style=COLOURS["dim"])
            )
            return
        widths = {
            "icon": GLYPH_WIDTHS["icon"],
            "id": layout.atomic_widths["id"],
            "title": layout.flexible_width,
            "turns": layout.atomic_widths["turns"],
            "time": layout.atomic_widths["time"],
            "cost": layout.atomic_widths["cost"],
        }
        apply_widths(table, widths)

    def _selected_id(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        return cell_key.row_key.value

    def _render_hierarchy(self, rows, multi_pass, initial) -> None:
        self._last_rows = rows
        self._last_multi_pass = multi_pass
        self._sync_active_glyph_animation()
        table = self.query_one(HierarchyPagingTable)
        shape = tuple(r.node.id for r in rows)
        layout = self._hierarchy_layout(table, rows)
        if (
            shape == self._last_hierarchy_shape
            and not initial
            and not self._hierarchy_needs_rebuild
            and layout.stacked == self._hierarchy_stacked
        ):
            self._update_hierarchy_cells(table, rows, multi_pass)
            return

        self._hierarchy_floor = bool(rows) and layout.floor
        self._hierarchy_stacked = layout.stacked
        if self._hierarchy_floor:
            self._hierarchy_needs_rebuild = True
            self.query_one("#hierarchy-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["workflow"])), style=COLOURS["dim"])
            )
            return
        self._hierarchy_needs_rebuild = False

        selected_id = self._selected_id(table) or self._hierarchy_target_id
        table.clear(columns=True)
        row_budget = render_screen_row_budget(table, layout, len(COLUMN_GRIDS["workflow"]))
        self._hierarchy_layout_cache = layout
        self._hierarchy_row_budget_cache = row_budget
        store = self._container.store
        now = self._now().isoformat()
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
        else:
            widths = {
                "icon": GLYPH_WIDTHS["icon"],
                "id": layout.atomic_widths["id"],
                "title": layout.flexible_width,
                "turns": layout.atomic_widths["turns"],
                "time": layout.atomic_widths["time"],
                "cost": layout.atomic_widths["cost"],
            }
            for key in COLUMN_GRIDS["workflow"]:
                table.add_column(key, width=widths[key], key=key)

        ids = [r.node.id for r in rows]
        index = ids.index(selected_id) if selected_id in ids else 0
        active_frame = self._active_glyph_char()
        for row in rows:
            table.add_row(
                *hierarchy_row_cells(
                    row, layout, row_budget, active_frame=active_frame,
                    flow_service=self._flow_service, multi_pass=multi_pass,
                    store=store, now=now, pool_running=self._pool_running,
                ),
                height=None, key=row.node.id
            )

        self._last_hierarchy_shape = shape
        if rows:
            table.move_cursor(row=index)
        self.update_pinned_ancestor()

    def _update_hierarchy_cells(self, table, rows, multi_pass) -> None:
        table_ = self.query_one(HierarchyPagingTable)
        layout = self._hierarchy_layout(table_, rows)
        row_budget = render_screen_row_budget(table_, layout, len(COLUMN_GRIDS["workflow"]))
        self._hierarchy_layout_cache = layout
        self._hierarchy_row_budget_cache = row_budget
        store = self._container.store
        now = self._now().isoformat()
        active_frame = self._active_glyph_char()
        for row in rows:
            cells = hierarchy_row_cells(
                row, layout, row_budget, active_frame=active_frame,
                flow_service=self._flow_service, multi_pass=multi_pass,
                store=store, now=now, pool_running=self._pool_running,
            )
            if layout.stacked:
                table.update_cell(row.node.id, STACKED_COLUMN_KEY, cells[0])
                continue
            for key, value in zip(COLUMN_GRIDS["workflow"], cells):
                table.update_cell(row.node.id, key, value)

    def _active_glyph_char(self) -> str:
        return ACTIVE_GLYPH_FRAMES[self._active_glyph_frame]

    def _active_glyph_ids(self):
        return tuple(
            r.node.id for r in self._last_rows
            if row_bucket(r.node, _flow_for_bucket(r.node, self._flow_service), self._pool_running) == "active"
        )

    def _sync_active_glyph_animation(self) -> None:
        should_run = (
            self._active_tab == "workflow"
            and self.is_current
            and bool(self._active_glyph_ids())
            and not self._hierarchy_floor
        )
        if should_run and self._active_glyph_timer is None:
            self._active_glyph_timer = self.set_interval(
                1 / ACTIVE_GLYPH_TICKS_PER_SECOND, self._tick_active_glyph
            )
        elif not should_run and self._active_glyph_timer is not None:
            self._active_glyph_timer.stop()
            self._active_glyph_timer = None
            self._active_glyph_frame = ACTIVE_GLYPH_REST_INDEX

    def _tick_active_glyph(self) -> None:
        self._active_glyph_frame = next_active_glyph_frame(self._active_glyph_frame)
        active_ids = self._active_glyph_ids()
        if not active_ids or self._hierarchy_layout_cache is None:
            return
        table = self.query_one(HierarchyPagingTable)
        frame = self._active_glyph_char()
        layout = self._hierarchy_layout_cache
        row_budget = self._hierarchy_row_budget_cache
        store = self._container.store
        now = self._now().isoformat()
        rows_by_id = {r.node.id: r for r in self._last_rows}
        for node_id in active_ids:
            row = rows_by_id.get(node_id)
            if row is None:
                continue
            cells = hierarchy_row_cells(
                row, layout, row_budget, active_frame=frame, flow_service=self._flow_service,
                multi_pass=self._last_multi_pass, store=store, now=now,
                pool_running=self._pool_running,
            )
            try:
                if layout.stacked:
                    table.update_cell(node_id, STACKED_COLUMN_KEY, cells[0])
                else:
                    table.update_cell(node_id, "icon", cells[0])
            except CellDoesNotExist:
                pass
        self.update_pinned_ancestor()
