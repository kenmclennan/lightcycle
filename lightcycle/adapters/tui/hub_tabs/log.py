from lightcycle.adapters.log_parser import LogLineParser
from lightcycle.adapters.tui.design_system import COLOURS
from lightcycle.application.pool import (
    TailLogInput,
    TailLogUseCase,
)
from lightcycle.domain.work import LogKind
from rich.text import Text
from textual.widgets import Static
from lightcycle.adapters.tui.hub_render import (
    LOG_CURSOR_GLYPH,
    LOG_FINISHED_MESSAGE,
    LOG_INITIAL_TAIL_BYTES,
    LOG_LINES_MAX_RETAINED,
    LOG_NO_STREAM_MESSAGE,
    LOG_TAIL_INTERVAL_SECONDS,
    log_tab_mode,
)
from lightcycle.adapters.tui.hub_widgets import LogPane


class LogTabMixin:
    def _setup_log_tab(self) -> None:
        store = self._container.store
        node = store.get_node(self._node_id)
        log_node = node if node.type == "step" else None
        mode = log_tab_mode(log_node)
        self._log_mode = mode
        self._log_parser = LogLineParser()
        self._log_lines = []
        self._show_thinking = True
        empty = self.query_one("#hub-log-empty", Static)
        if mode == "no-log":
            empty.update(LOG_NO_STREAM_MESSAGE)
            return
        self._log_target = log_node.id
        log_pane = self.query_one(LogPane)
        log_pane.live = mode == "live"
        log_pane.auto_scroll = mode == "live"
        result = self._run_initial_tail()
        if result.path is None:
            self._log_mode = "no-log"
            empty.update(LOG_NO_STREAM_MESSAGE)
            return
        self._apply_tail_result(result)
        if self._log_mode == "live" and not self._log_finished:
            self._log_timer = self.set_interval(LOG_TAIL_INTERVAL_SECONDS, self._tail_tick)

    def _run_initial_tail(self):
        use_case = TailLogUseCase(
            self._container.store, self._container.workers, self._container.worker_log,
            self._container.fs, self._container.config
        )
        return use_case.execute(TailLogInput(target=self._log_target, max_bytes=LOG_INITIAL_TAIL_BYTES))

    def _run_tail(self, offset):
        use_case = TailLogUseCase(
            self._container.store, self._container.workers, self._container.worker_log,
            self._container.fs, self._container.config
        )
        return use_case.execute(TailLogInput(target=self._log_target, offset=offset))

    def _tail_tick(self) -> None:
        self._apply_tail_result(self._run_tail(self._log_offset))

    def _apply_tail_result(self, result) -> None:
        self._log_offset = result.offset
        log_pane = self.query_one(LogPane)
        new_lines = self._log_parser.feed(result.data) if result.data else []
        if new_lines:
            self._log_lines = (self._log_lines + new_lines)[-LOG_LINES_MAX_RETAINED:]
            retained_new = new_lines[max(0, len(new_lines) - LOG_LINES_MAX_RETAINED):]
            self._write_tail_data(log_pane, retained_new)
        if self._log_mode == "live" and not result.live and not self._log_finished:
            self._clear_log_cursor(log_pane)
            self._log_finished = True
            log_pane.live = False
            log_pane.write(Text(LOG_FINISHED_MESSAGE, style=COLOURS["cyan"]))
            if self._log_timer is not None:
                self._log_timer.stop()

    def _visible_log_lines(self, lines):
        if self._show_thinking:
            return list(lines)
        return [line for line in lines if line.kind != LogKind.THINKING]

    def _render_log_line(self, line) -> Text:
        prefix = line.timestamp.astimezone().strftime("%H:%M:%S ") if line.timestamp else ""
        return Text(prefix + line.text, style=COLOURS["text"])

    def _paint_log_lines(self, log_pane, lines, live) -> None:
        for index, line in enumerate(lines):
            content = self._render_log_line(line)
            if live and index == len(lines) - 1:
                cursor_content = Text.assemble(content, (LOG_CURSOR_GLYPH, COLOURS["cyan"]))
                self._log_cursor_row_count = log_pane.write_entry(cursor_content)
                self._log_cursor_text = content
                self._log_cursor_active = True
            else:
                log_pane.write_entry(content)

    def _write_tail_data(self, log_pane, lines) -> None:
        visible = self._visible_log_lines(lines)
        if not visible:
            return
        live = self._log_mode == "live" and not self._log_finished
        if live:
            self._clear_log_cursor(log_pane)
        self._paint_log_lines(log_pane, visible, live)

    def _clear_log_cursor(self, log_pane) -> None:
        if not self._log_cursor_active:
            return
        log_pane.replace_last_entry(self._log_cursor_row_count, self._log_cursor_text)
        self._log_cursor_active = False

    def action_toggle_thinking(self) -> None:
        if self._active_tab != "log" or self._log_mode == "no-log":
            return
        self._show_thinking = not self._show_thinking
        log_pane = self.query_one(LogPane)
        log_pane.clear()
        self._log_cursor_active = False
        visible = self._visible_log_lines(self._log_lines)
        live = self._log_mode == "live" and not self._log_finished
        self._paint_log_lines(log_pane, visible, live)
