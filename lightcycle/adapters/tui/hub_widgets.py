from lightcycle.adapters.tui.design_system import COLOURS
from lightcycle.adapters.tui.hub_render import (
    LOG_PANE_MAX_LINES,
    _TAB_LABELS,
    _context_text,
    _identity_text,
    _row_node,
    escalation_panel_text,
    escalation_reason_text,
    log_tab_mode,
)
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import (
    Horizontal,
    Vertical,
    VerticalScroll,
)
from textual.widgets import (
    DataTable,
    RichLog,
    Static,
)
from textual.widgets.data_table import CellDoesNotExist


class HubScreenMarker:
    pass


class EscalationPanel(Static):
    def on_resize(self, event: events.Resize) -> None:
        header = self.parent
        if isinstance(header, HubHeader) and header._last_header is not None:
            header._paint_escalation(header._last_header)


class HubHeader(Vertical):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_header = None

    def compose(self) -> ComposeResult:
        yield Static(id="hub-identity")
        yield Static(id="hub-context")
        yield EscalationPanel(id="hub-escalation")

    def update(self, header) -> None:
        self.query_one("#hub-identity", Static).update(_identity_text(header))
        context = self.query_one("#hub-context", Static)
        text = _context_text(header, context.screen.size.width)
        if text:
            context.update(Text(text, style=COLOURS["dim"]))
            context.display = True
        else:
            context.update("")
            context.display = False

        self._last_header = header
        self._paint_escalation(header)

    def _paint_escalation(self, header) -> None:
        panel = self.query_one(EscalationPanel)
        if header.escalation_text:
            is_demand = header.escalation_target is None
            width = max(1, panel.size.width)
            painted = escalation_panel_text() if is_demand else escalation_reason_text(header, width)
            panel.update(painted)
            panel.display = True
        else:
            panel.update("")
            panel.display = False


class HubTabStrip(Horizontal):
    def __init__(self, tabs, active, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tabs = tabs
        self._active = active

    def compose(self) -> ComposeResult:
        for tab in self._tabs:
            classes = "tab-active" if tab == self._active else "tab-dim"
            yield Static(_TAB_LABELS[tab], id="hub-tab-%s" % tab, classes=classes)

    def set_active(self, active) -> None:
        for tab in self._tabs:
            widget = self.query_one("#hub-tab-%s" % tab, Static)
            widget.set_class(tab == active, "tab-active")
            widget.set_class(tab != active, "tab-dim")


class LogPane(RichLog):
    BINDINGS = [
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("wrap", True)
        kwargs.setdefault("min_width", 0)
        kwargs.setdefault("max_lines", LOG_PANE_MAX_LINES)
        super().__init__(*args, **kwargs)
        self.live = False

    def watch_scroll_y(self, old, new) -> None:
        super().watch_scroll_y(old, new)
        self.auto_scroll = self.is_vertical_scroll_end

    def write_entry(self, content) -> int:
        before_deferred = len(self._deferred_renders)
        before = len(self.lines) + self._start_line
        self.write(content)
        if len(self._deferred_renders) > before_deferred:
            return 1
        return len(self.lines) + self._start_line - before

    def replace_last_entry(self, row_count, content) -> None:
        for _ in range(row_count):
            if self._deferred_renders:
                self._deferred_renders.pop()
            elif self.lines:
                self.lines.pop()
        self._line_cache.clear()
        self.write(content, scroll_end=False)


class HierarchyPagingTable(DataTable):
    _BASE = [b for b in DataTable.BINDINGS if b.key not in ("left", "right")]

    BINDINGS = _BASE + [
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("right", "select_cursor", "Open", show=False),
        Binding("o", "jump_outputs", "Outputs", show=False),
        Binding("l", "jump_log", "Log", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)

    def watch_scroll_y(self, old, new) -> None:
        super().watch_scroll_y(old, new)
        if isinstance(self.screen, HubScreenMarker):
            self.screen.update_pinned_ancestor()

    def watch_cursor_coordinate(self, old_coordinate, new_coordinate) -> None:
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)
        if isinstance(self.screen, HubScreenMarker):
            self.screen.update_pinned_ancestor()

    def _highlighted_id(self):
        if self.row_count == 0:
            return None
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
        except CellDoesNotExist:
            return None
        return cell_key.row_key.value

    def action_jump_outputs(self) -> None:
        row_id = self._highlighted_id()
        if row_id is None or not isinstance(self.screen, HubScreenMarker):
            return
        node = _row_node(self.screen._last_rows, row_id)
        if node is None or node.type != "item":
            return
        self.screen.switch_at(row_id, initial_tab="outputs")

    def action_jump_log(self) -> None:
        row_id = self._highlighted_id()
        if row_id is None or not isinstance(self.screen, HubScreenMarker):
            return
        node = _row_node(self.screen._last_rows, row_id)
        if node is None or node.type != "step":
            return
        if log_tab_mode(node) == "no-log":
            return
        self.screen.switch_at(row_id, initial_tab="log")

    def on_resize(self, event: events.Resize) -> None:
        screen = self.screen
        if isinstance(screen, HubScreenMarker):
            screen.refresh_hierarchy_width()

    def _page_height(self) -> int:
        height = self.scrollable_content_region.height - (
            self.header_height if self.show_header else 0
        )
        if isinstance(self.screen, HubScreenMarker):
            banner = self.screen.query_one("#pinned-ancestor", Static)
            if banner.display:
                height += 1
        return height

    def action_page_down(self) -> None:
        self._set_hover_cursor(False)
        if self.show_cursor and self.cursor_type in ("cell", "row"):
            height = self._page_height()
            offset = 0
            rows_to_scroll = 0
            row_index, _ = self.cursor_coordinate
            for ordered_row in self.ordered_rows[row_index:]:
                offset += ordered_row.height
                rows_to_scroll += 1
                if offset > height:
                    break
            target_row = row_index + rows_to_scroll - 1
            self.scroll_relative(y=height, animate=False, force=True)
            self.move_cursor(row=target_row, scroll=False)
        else:
            super().action_page_down()

    def action_page_up(self) -> None:
        self._set_hover_cursor(False)
        if self.show_cursor and self.cursor_type in ("cell", "row"):
            height = self._page_height()
            offset = 0
            rows_to_scroll = 0
            row_index, _ = self.cursor_coordinate
            for ordered_row in self.ordered_rows[: row_index + 1]:
                offset += ordered_row.height
                rows_to_scroll += 1
                if offset > height:
                    break
            target_row = row_index - rows_to_scroll + 1
            self.scroll_relative(y=-height, animate=False)
            self.move_cursor(row=target_row, scroll=False)
        else:
            super().action_page_up()


class OutputsTable(DataTable):
    _BASE = [b for b in DataTable.BINDINGS if b.key not in ("left", "right")]

    BINDINGS = _BASE + [
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("right", "select_cursor", "Open", show=False),
        Binding("space", "toggle_history", "History", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)

    def action_toggle_history(self) -> None:
        screen = self.screen
        if isinstance(screen, HubScreenMarker):
            screen.toggle_output_history()

    def on_resize(self, event: events.Resize) -> None:
        screen = self.screen
        if isinstance(screen, HubScreenMarker):
            screen.refresh_outputs_width()


class DetailTable(DataTable):
    _BASE = [b for b in DataTable.BINDINGS if b.key not in ("left", "right")]

    BINDINGS = _BASE + [
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("right", "select_cursor", "Open", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)

    def on_resize(self, event: events.Resize) -> None:
        screen = self.screen
        if isinstance(screen, HubScreenMarker):
            screen.refresh_detail_width()


class ContextList(VerticalScroll, can_focus=False):
    pass


class ContextTable(DataTable):
    _BASE = [b for b in DataTable.BINDINGS if b.key not in ("left", "right")]

    BINDINGS = _BASE + [
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("right", "select_cursor", "Open", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)

    def action_cursor_down(self) -> None:
        self.screen.step_context_cursor(1)

    def action_cursor_up(self) -> None:
        self.screen.step_context_cursor(-1)

    def action_page_down(self) -> None:
        self.screen.page_context_cursor(1)

    def action_page_up(self) -> None:
        self.screen.page_context_cursor(-1)

    def action_scroll_home(self) -> None:
        self.screen.jump_context_cursor(first=True)

    def action_scroll_top(self) -> None:
        self.screen.jump_context_cursor(first=True)

    def action_scroll_end(self) -> None:
        self.screen.jump_context_cursor(first=False)

    def action_scroll_bottom(self) -> None:
        self.screen.jump_context_cursor(first=False)

    def on_resize(self, event: events.Resize) -> None:
        screen = self.screen
        if isinstance(screen, HubScreenMarker):
            screen.refresh_context_width()


class CostPane(RichLog):
    BINDINGS = [
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
    ]

    def on_resize(self, event: events.Resize) -> None:
        screen = self.screen
        if isinstance(screen, HubScreenMarker):
            screen.refresh_cost_width()


class DescriptionPane(RichLog):
    BINDINGS = [
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
    ]

    def on_resize(self, event: events.Resize) -> None:
        screen = self.screen
        if isinstance(screen, HubScreenMarker):
            screen.refresh_description_width()


def pane_text_width(pane) -> int:
    if not pane.size.width:
        return 0
    return max(pane.size.width - pane.styles.scrollbar_size_vertical, 1)
