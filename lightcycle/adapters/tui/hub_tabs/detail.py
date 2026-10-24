from lightcycle.adapters.tui.design_system import (
    COLOURS,
    COLUMN_GRIDS,
)
from lightcycle.adapters.tui.prose_text import resolve_titles
from lightcycle.adapters.tui.row_grid import (
    apply_widths,
    compute_layout,
    floor_message,
    render_screen_row_budget,
    screen_row_budget_for,
)
from lightcycle.application.errors import UseCaseError
from lightcycle.application.work import (
    StepRunInput,
    StepRunUseCase,
)
from lightcycle.application.work.step_detail import StepDetail
from lightcycle.application.work.step_inputs import StepInputs
from rich.text import Text
from textual.widgets import Static
from textual.widgets.data_table import CellDoesNotExist
from lightcycle.adapters.tui.hub_render import (
    DETAIL_CONTINUATION_INDENT,
    STACKED_COLUMN_KEY,
    _detail_field_label,
    detail_fields,
    detail_row_cells,
    detail_value_is_block,
    PARK_PANEL_TITLE,
    park_panel_text,
    shorten_home,
)
from lightcycle.adapters.tui.hub_widgets import DetailTable


class DetailTabMixin:
    def refresh_detail_width(self) -> None:
        table = self.query_one(DetailTable)
        if not self._last_detail_fields:
            return
        layout = self._detail_layout(table, self._last_detail_fields)
        if layout.floor != self._detail_floor or layout.stacked != self._detail_stacked or layout.stacked:
            self._render_detail_fields(self._last_detail_fields, initial=True)
            self._apply_tab_visibility()
            return
        if layout.floor:
            self.query_one("#detail-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["detail"])), style=COLOURS["dim"])
            )
            return
        apply_widths(table, {"key": layout.atomic_widths["key"], "value": layout.flexible_width})

    def _detail_layout(self, table, fields):
        atomic_values = {"key": [_detail_field_label(key) for key, _value in fields]}
        row_budget = screen_row_budget_for(table, len(COLUMN_GRIDS["detail"]))
        return compute_layout(row_budget, [], atomic_values, indent=DETAIL_CONTINUATION_INDENT)

    def _fields_for(self, store, step, flow_service):
        run = StepRunUseCase(store, flow_service).execute(StepRunInput(step=step.id))
        step_inputs = StepInputs(store, flow_service)
        entries, _presents = StepDetail(store, flow_service).resolve(
            step, step_inputs.read(step), step_inputs.entry_dicts_for_step(step), run=run,
            worktree=self._worktree_path_for(run, flow_service))
        return detail_fields(entries)

    def _render_detail(self, store, step, initial) -> None:
        fields = self._fields_for(store, step, self._flow_service)
        self._detail_empty = not fields
        self._detail_park = park_panel_text(step.park, self._home_dir())
        panel = self.query_one("#hub-detail-park", Static)
        panel.border_title = PARK_PANEL_TITLE
        panel.update(self._detail_park or "")
        self._render_detail_fields(fields, initial)

    def _home_dir(self):
        return self._container.config.expand_path("~")

    def _worktree_path_for(self, run, flow_service):
        if not run.branch:
            return None
        try:
            return self._container.worktrees(flow=flow_service).path_for_run(run)
        except UseCaseError:
            return None

    def _detail_rows(self, fields, layout, row_budget):
        blocks = "\n".join(value for _key, value in fields if detail_value_is_block(value))
        titles = resolve_titles(self._container.store, blocks)
        home = self._home_dir()
        rows = []
        for key, value in fields:
            field = (key, shorten_home(value, home) if key == "worktree" else value)
            rows.extend(detail_row_cells(field, layout, row_budget, titles))
        return rows

    def _render_detail_fields(self, fields, initial) -> None:
        self._last_detail_fields = fields
        table = self.query_one(DetailTable)
        layout = self._detail_layout(table, fields)
        row_budget = render_screen_row_budget(table, layout, len(COLUMN_GRIDS["detail"]))
        rows = self._detail_rows(fields, layout, row_budget)
        shape = tuple(k for k, _cells in rows)
        if (
            shape == self._last_detail_shape
            and not initial
            and not self._detail_needs_rebuild
            and layout.stacked == self._detail_stacked
        ):
            self._update_detail_cells(table, rows)
            return

        self._detail_floor = bool(fields) and layout.floor
        self._detail_stacked = layout.stacked
        if self._detail_floor:
            self._detail_needs_rebuild = True
            self.query_one("#detail-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["detail"])), style=COLOURS["dim"])
            )
            return
        self._detail_needs_rebuild = False

        selected_key = self._selected_detail_key(table)
        table.clear(columns=True)
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
        else:
            widths = {"key": layout.atomic_widths["key"], "value": layout.flexible_width}
            for key in COLUMN_GRIDS["detail"]:
                table.add_column(key, width=widths[key], key=key)

        for row_key, cells in rows:
            table.add_row(*cells, height=None, key=row_key)

        self._last_detail_shape = shape
        if rows:
            keys = [row_key for row_key, _cells in rows]
            index = keys.index(selected_key) if selected_key in keys else 0
            table.move_cursor(row=index)

    def _selected_detail_key(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        return cell_key.row_key.value

    def _update_detail_cells(self, table, rows) -> None:
        columns = (STACKED_COLUMN_KEY,) if self._detail_stacked else COLUMN_GRIDS["detail"]
        for row_key, cells in rows:
            for key, value in zip(columns, cells):
                table.update_cell(row_key, key, value)
