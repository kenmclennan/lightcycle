from lightcycle.adapters.tui.design_system import (
    COLOURS,
    COLUMN_GRIDS,
)
from lightcycle.adapters.tui.row_grid import (
    apply_widths,
    compute_layout,
    floor_message,
    render_screen_row_budget,
    screen_row_budget_for,
)
from lightcycle.application.work.item_output_rows import ItemOutputRows
from lightcycle.domain.work.output_rows import output_lines
from rich.text import Text
from textual.widgets import Static
from textual.widgets.data_table import CellDoesNotExist
from lightcycle.adapters.tui.hub_render import (
    OUTPUTS_CONTINUATION_INDENT,
    STACKED_COLUMN_KEY,
    _output_name_text,
    output_row_cells,
)
from lightcycle.adapters.tui.hub_widgets import OutputsTable


class OutputsTabMixin:
    def refresh_outputs_width(self) -> None:
        table = self.query_one(OutputsTable)
        if not self._last_outputs:
            return
        layout = self._outputs_layout(table, self._last_outputs)
        if layout.floor != self._outputs_floor or layout.stacked != self._outputs_stacked or layout.stacked:
            self._render_output_lines(self._last_outputs, initial=True)
            self._apply_tab_visibility()
            return
        if layout.floor:
            self.query_one("#outputs-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["outputs"])), style=COLOURS["dim"])
            )
            return
        apply_widths(table, {
            "name": layout.atomic_widths["name"], "value": layout.flexible_width,
            "step": layout.atomic_widths["step"], "pass": layout.atomic_widths["pass"],
        })

    def _outputs_layout(self, table, lines):
        gap = "  "
        atomic_values = {
            "name": [_output_name_text(line) + gap for line in lines],
            "step": [(line.step or "") + gap for line in lines],
            "pass": [line.pass_text for line in lines],
        }
        row_budget = screen_row_budget_for(table, len(COLUMN_GRIDS["outputs"]))
        return compute_layout(row_budget, [], atomic_values, indent=OUTPUTS_CONTINUATION_INDENT)

    def _selected_output_index(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        value = cell_key.row_key.value
        return int(value) if value is not None else None

    def _render_outputs(self, rows, initial) -> None:
        self._output_rows = rows
        self._render_output_lines(
            output_lines(rows, self._expanded_outputs), initial
        )

    def _render_output_lines(self, lines, initial, select_key=None) -> None:
        self._last_outputs = lines
        self._has_outputs = bool(lines)
        table = self.query_one(OutputsTable)
        layout = self._outputs_layout(table, lines)
        if (
            tuple(lines) == self._last_outputs_shape
            and not initial
            and not self._outputs_needs_rebuild
            and layout.stacked == self._outputs_stacked
        ):
            self._last_outputs_shape = tuple(lines)
            self._update_output_cells(table, lines)
            return

        self._outputs_floor = bool(lines) and layout.floor
        self._outputs_stacked = layout.stacked
        if self._outputs_floor:
            self._outputs_needs_rebuild = True
            self.query_one("#outputs-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["outputs"])), style=COLOURS["dim"])
            )
            return
        self._outputs_needs_rebuild = False

        selected_index = self._selected_output_index(table)
        table.clear(columns=True)
        row_budget = render_screen_row_budget(table, layout, len(COLUMN_GRIDS["outputs"]))
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
        else:
            widths = {
                "name": layout.atomic_widths["name"], "value": layout.flexible_width,
                "step": layout.atomic_widths["step"], "pass": layout.atomic_widths["pass"],
            }
            for key in COLUMN_GRIDS["outputs"]:
                table.add_column(key, width=widths[key], key=key)

        for index, line in enumerate(lines):
            table.add_row(*output_row_cells(line, layout, row_budget), height=None, key=str(index))

        self._last_outputs_shape = tuple(lines)
        if lines:
            if select_key is not None:
                selected_index = next(
                    (i for i, line in enumerate(lines) if line.row_key == select_key), None
                )
            has_selection = selected_index is not None and selected_index < len(lines)
            table.move_cursor(row=selected_index if has_selection else 0)

    def toggle_output_history(self) -> None:
        table = self.query_one(OutputsTable)
        index = self._selected_output_index(table)
        if index is None or index >= len(self._last_outputs):
            return
        line = self._last_outputs[index]
        owner = next((r for r in self._output_rows if r.key == line.row_key), None)
        if owner is None or not owner.history:
            return
        self._expanded_outputs.symmetric_difference_update({line.row_key})
        self._render_output_lines(
            output_lines(self._output_rows, self._expanded_outputs), initial=True,
            select_key=line.row_key,
        )

    def _update_output_cells(self, table, lines) -> None:
        layout = self._outputs_layout(table, lines)
        row_budget = render_screen_row_budget(table, layout, len(COLUMN_GRIDS["outputs"]))
        for index, line in enumerate(lines):
            cells = output_row_cells(line, layout, row_budget)
            if layout.stacked:
                table.update_cell(str(index), STACKED_COLUMN_KEY, cells[0])
                continue
            for key, value in zip(COLUMN_GRIDS["outputs"], cells):
                table.update_cell(str(index), key, value)

    def _item_output_rows(self, store, item):
        return ItemOutputRows(store, self._flow_service).for_item(item)
