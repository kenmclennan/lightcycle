from lightcycle.adapters.tui.design_system import (
    COLOURS,
    COLUMN_GRIDS,
    HEADING_STYLE,
)
from lightcycle.adapters.tui.prose_text import resolve_titles
from lightcycle.adapters.tui.row_grid import (
    compute_layout,
    floor_message,
    render_screen_row_budget,
    screen_row_budget_for,
)
from lightcycle.application.work.step_context import (
    SECTION_INPUTS,
    StepContext,
)
from rich.text import Text
from textual import events
from textual.geometry import Region
from textual.widgets import Static
from lightcycle.adapters.tui.hub_render import (
    CONTEXT_CONTINUATION_INDENT,
    CONTEXT_SECTIONS,
    STACKED_COLUMN_KEY,
    context_row_cells,
    context_row_key,
    context_section_rows,
    context_section_title,
)
from lightcycle.adapters.tui.hub_widgets import (
    ContextList,
    ContextTable,
)


class ContextTabMixin:
    def _context_tables(self):
        return list(self.query(ContextTable))

    def _visible_context_tables(self):
        return [t for t in self._context_tables() if t.row_count]

    def _context_entries(self):
        return [(t, row) for t in self._visible_context_tables() for row in range(t.row_count)]

    def _active_context_table(self):
        for table in self._visible_context_tables():
            if table.name == self._context_active:
                return table
        return None

    def _context_focus_target(self):
        return self._active_context_table() or next(iter(self._visible_context_tables()), None)

    def _activate_context_table(self, table) -> None:
        self._context_active = table.name
        for other in self._context_tables():
            other.show_cursor = other is table

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        widget = event.widget
        if isinstance(widget, ContextTable) and widget.name != self._context_active:
            self._activate_context_table(widget)

    def _context_position(self):
        table = self._active_context_table()
        if table is None:
            return None
        return self._context_entries().index((table, table.cursor_coordinate.row))

    def step_context_cursor(self, delta) -> None:
        position = self._context_position()
        if position is not None:
            self._goto_context(position + delta)

    def jump_context_cursor(self, first) -> None:
        self._goto_context(0 if first else len(self._context_entries()) - 1)

    def page_context_cursor(self, direction) -> None:
        position = self._context_position()
        if position is None:
            return
        entries = self._context_entries()
        viewport = max(self.query_one(ContextList).size.height, 1)
        travelled = 0
        target = position
        while 0 <= target + direction < len(entries) and travelled < viewport:
            target += direction
            table, row = entries[target]
            travelled += table.ordered_rows[row].height
        self._goto_context(target)

    def _goto_context(self, index) -> None:
        entries = self._context_entries()
        if not entries:
            return
        index = max(0, min(index, len(entries) - 1))
        table, row = entries[index]
        was_context_focus = isinstance(self.focused, ContextTable)
        self._activate_context_table(table)
        table.move_cursor(row=row, animate=False, scroll=False)
        if was_context_focus and self.focused is not table:
            self.set_focus(table, scroll_visible=False)
        self._scroll_context_to(table, row, index)

    def _scroll_context_to(self, table, row, index) -> None:
        context_list = self.query_one(ContextList)
        if index == 0:
            context_list.scroll_home(animate=False, immediate=True)
            return
        top = table.virtual_region.y + sum(r.height for r in table.ordered_rows[:row])
        bottom = top + table.ordered_rows[row].height
        if row == 0:
            top = self.query_one("#hub-context-header-%s" % table.name, Static).virtual_region.y
        context_list.scroll_to_region(
            Region(0, top, max(context_list.size.width, 1), bottom - top),
            animate=False,
            immediate=True,
        )

    def _context_layout(self, table, sections):
        data = [r for members in sections.values() for _key, r in members]
        atomic_values = {
            "key": [context_row_key(r) for r in data],
        }
        row_budget = screen_row_budget_for(table, len(COLUMN_GRIDS["context"]))
        return compute_layout(row_budget, [], atomic_values, indent=CONTEXT_CONTINUATION_INDENT)

    def _render_context(self, store, step, initial) -> None:
        view = StepContext(store, self._flow_service).read(step)
        self._last_context_rows = list(view.rows)
        self._has_context = any(r.value is not None or r.section != SECTION_INPUTS for r in view.rows)
        self._context_inputs_live = view.inputs_live
        self._context_reconstructed = view.reconstructed
        self._paint_context(initial)

    def refresh_context_width(self) -> None:
        if self._last_context_rows and self.size.width != self._context_width:
            self._paint_context(True)
            self._apply_tab_visibility()

    def _selected_context_key(self):
        table = self._active_context_table()
        return self._selected_detail_key(table) if table is not None else None

    def _paint_context(self, initial) -> None:
        sizing = self.query_one("#hub-context-table-%s" % SECTION_INPUTS, ContextTable)
        sections = context_section_rows(self._last_context_rows)
        layout = self._context_layout(sizing, sections)
        row_budget = render_screen_row_budget(sizing, layout, len(COLUMN_GRIDS["context"]))
        titles = resolve_titles(
            self._container.store, "\n".join(r.value or "" for r in self._last_context_rows)
        )
        cells = {
            section: [
                (key, context_row_cells(row, layout, row_budget, titles)) for key, row in members
            ]
            for section, members in sections.items()
        }
        shape = (
            tuple(
                (section, tuple((k, tuple(c.plain for c in cs)) for k, cs in rows))
                for section, rows in cells.items()
            ),
            layout.stacked,
            self._context_inputs_live,
        )
        if shape == self._last_context_shape and not initial and not self._context_needs_rebuild:
            return
        self._context_floor = layout.floor
        self._context_stacked = layout.stacked
        if self._context_floor:
            self._context_needs_rebuild = True
            self.query_one("#context-floor", Static).update(
                Text(floor_message(layout, sizing, len(COLUMN_GRIDS["context"])), style=COLOURS["dim"])
            )
            self._apply_tab_visibility()
            return
        self._context_needs_rebuild = False
        self._context_width = self.size.width
        selected_key = self._selected_context_key()
        for section in CONTEXT_SECTIONS:
            table = self.query_one("#hub-context-table-%s" % section, ContextTable)
            header = self.query_one("#hub-context-header-%s" % section, Static)
            none = self.query_one("#hub-context-none-%s" % section, Static)
            rows = cells[section]
            header.update(Text(context_section_title(section, self._context_inputs_live), style=HEADING_STYLE))
            header.set_class(section == SECTION_INPUTS, "first-visible")
            table.set_class(not rows, "hidden")
            none.set_class(bool(rows), "hidden")
            table.clear(columns=True)
            if layout.stacked:
                table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
            else:
                widths = {
                    "key": layout.atomic_widths["key"],
                    "value": layout.flexible_width,
                }
                for key in COLUMN_GRIDS["context"]:
                    table.add_column(key, width=widths[key], key=key)
            for row_key, row_cells in rows:
                table.add_row(*row_cells, height=None, key=row_key)
        self._last_context_shape = shape
        self._restore_context_cursor(selected_key)

    def _restore_context_cursor(self, selected_key) -> None:
        tables = self._visible_context_tables()
        if not tables:
            return
        target, index = tables[0], 0
        for table in tables:
            keys = [row.key.value for row in table.ordered_rows]
            if selected_key in keys:
                target, index = table, keys.index(selected_key)
                break
        was_context_focus = isinstance(self.focused, ContextTable)
        self._activate_context_table(target)
        target.move_cursor(row=index, animate=False, scroll=False)
        if was_context_focus and self.focused is not target:
            self.set_focus(target, scroll_visible=False)
