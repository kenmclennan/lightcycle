from lightcycle.adapters.tui.design_system import COLOURS
from lightcycle.adapters.tui.row_grid import compute_layout
from lightcycle.application.work import (
    CostInput,
    CostUseCase,
)
from rich.text import Text
from textual.widgets import Static
from lightcycle.adapters.tui.hub_render import (
    COST_COLUMN_GAP,
    COST_CONTINUATION_INDENT,
    COST_EMPTY_MESSAGE,
    COST_NOT_RUN_MESSAGE,
    ITEM_COST_EMPTY_MESSAGE,
    _cost_pane_screen_row_budget,
    _cost_row_text,
    _cost_rows_for_item,
    _cost_rows_for_step,
)
from lightcycle.adapters.tui.hub_widgets import CostPane


class CostTabMixin:
    def _cost_layout(self, pane, rows):
        atomic_values = {"key": [label for _key, label, _value in rows if label]}
        row_budget = _cost_pane_screen_row_budget(pane, 2)
        return compute_layout(row_budget, [], atomic_values, indent=COST_CONTINUATION_INDENT)

    def _cost_floor_message(self, layout, pane):
        chrome = pane.screen.outer_size.width - pane.screen.size.width
        needed = layout.floor_width + COST_COLUMN_GAP + chrome + pane.scrollbar_gutter.width
        return "Widen the terminal to at least %d columns to show this list." % needed

    def _render_cost(self, store, node, initial) -> None:
        cost = CostUseCase(store).execute(CostInput(node=node.id))
        if node.type == "step":
            self._render_step_cost(cost, initial)
        else:
            self._render_item_cost(cost, initial)

    def _set_cost_whole_empty(self, message, initial) -> None:
        self._cost_whole_empty_message = message
        self.query_one("#hub-cost-empty", Static).update(message)
        self._render_cost_pane([], initial)

    def _render_step_cost(self, cost, initial) -> None:
        if not cost.applicable:
            self._set_cost_whole_empty(COST_EMPTY_MESSAGE, initial)
            return
        if not cost.has_run:
            self._set_cost_whole_empty(COST_NOT_RUN_MESSAGE, initial)
            return
        self._cost_whole_empty_message = None
        self._render_cost_pane(_cost_rows_for_step(cost), initial)

    def _render_item_cost(self, cost, initial) -> None:
        if cost.turn_count == 0:
            self._set_cost_whole_empty(ITEM_COST_EMPTY_MESSAGE, initial)
            return
        self._cost_whole_empty_message = None
        self._render_cost_pane(_cost_rows_for_item(cost), initial)

    def _render_cost_pane(self, rows, initial) -> None:
        self._last_cost_rows = rows
        if not rows:
            self._last_cost_shape = None
            self._cost_floor = False
            return
        pane = self.query_one(CostPane)
        shape = tuple(rows)
        if shape == self._last_cost_shape and not initial:
            return

        layout = self._cost_layout(pane, rows)
        self._cost_floor = layout.floor
        self._cost_stacked = layout.stacked
        pane.clear()
        if self._cost_floor:
            self.query_one("#cost-floor", Static).update(
                Text(self._cost_floor_message(layout, pane), style=COLOURS["dim"])
            )
            self._last_cost_shape = shape
            return

        row_budget = (
            _cost_pane_screen_row_budget(pane, 1) if layout.stacked else _cost_pane_screen_row_budget(pane, 2)
        )
        for _key, label, value in rows:
            pane.write(_cost_row_text(label, value, layout, row_budget))
        self._last_cost_shape = shape

    def refresh_cost_width(self) -> None:
        rows = self._last_cost_rows
        if not rows:
            return
        self._render_cost_pane(rows, initial=True)
        self._apply_tab_visibility()
