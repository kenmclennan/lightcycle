from lightcycle.adapters.log_parser import LogLineParser
from lightcycle.adapters.tui.design_system import COLOURS
from lightcycle.application.pool import (
    EarlierLogInput,
    ReadEarlierLogUseCase,
    TailLogInput,
    TailLogUseCase,
)
from lightcycle.domain.work import LogKind, LogLine, StepSession, session_separator
from rich.text import Text
from textual.widgets import Static
from lightcycle.adapters.tui.hub_render import (
    LOG_CURSOR_GLYPH,
    LOG_EARLIER_NOT_LOADED_MESSAGE,
    LOG_FINISHED_MESSAGE,
    LOG_INITIAL_TAIL_BYTES,
    LOG_LINES_MAX_RETAINED,
    LOG_NO_STREAM_MESSAGE,
    LOG_PAGE_BYTES,
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
        self._log_spans = []
        self._log_trimmed = False
        self._log_paged = False
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
        self._log_path = result.path
        self._seed_log_state(result)
        self._apply_tail_result(result, paint=False)
        self._repaint_log()
        if self._log_mode == "live" and not self._log_finished:
            self._log_timer = self.set_interval(LOG_TAIL_INTERVAL_SECONDS, self._tail_tick)

    def _seed_log_state(self, result) -> None:
        sessions = self._container.store.step_sessions(self._log_target)
        newest = sessions[-1].n if sessions else 1
        self._log_first_session = sessions[0].n if sessions else 1
        start = result.offset - len(result.data)
        self._log_cursor = (newest, start)
        self._log_spans = [(newest, start, None)]
        lines = []
        if start == 0 and newest > 1:
            budget = LOG_INITIAL_TAIL_BYTES - len(result.data)
            earlier = ReadEarlierLogUseCase(
                self._container.store, self._container.worker_log, self._container.fs
            ).execute(EarlierLogInput(
                target=self._log_target, session=newest, offset=0, max_bytes=budget,
                fallback_path=result.path))
            lines = self._take_chunks(earlier.chunks, sessions)
            lines.append(self._separator_for(sessions[-1], sessions))
        self._log_lines = lines

    def _take_chunks(self, chunks, sessions):
        lines = []
        spans = []
        for chunk in chunks:
            lines.extend(self._chunk_lines(chunk, sessions))
            spans.append((chunk.session.n, chunk.start, chunk.start + len(chunk.data)))
        if chunks:
            self._log_spans = spans + self._log_spans
            self._log_cursor = (chunks[0].session.n, chunks[0].start)
        return lines

    def _separator_for(self, session, sessions):
        previous = [s for s in sessions if s.n == session.n - 1]
        reason = previous[0].ended_reason if previous else None
        return self._separator_line(session, len(sessions), reason)

    def _chunk_lines(self, chunk, sessions):
        lines = []
        if chunk.start == 0 and chunk.session.n > 1:
            lines.append(self._separator_for(chunk.session, sessions))
        if chunk.exists:
            lines.extend(LogLineParser().feed(chunk.data) if chunk.data else [])
        else:
            lines.append(self._not_found_line(chunk.session))
        return lines

    def _not_found_line(self, session):
        return LogLine(
            timestamp=None, kind=LogKind.SESSION,
            text="(log file not found: %s)" % session.log_path)

    def _separator_line(self, session, total, previous_reason):
        return LogLine(
            timestamp=None, kind=LogKind.SESSION,
            text=session_separator(session, total, previous_reason))

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

    def _apply_tail_result(self, result, paint=True) -> None:
        self._log_offset = result.offset
        log_pane = self.query_one(LogPane)
        new_lines = self._log_parser.feed(result.data) if result.data else []
        if new_lines:
            combined = self._log_lines + new_lines
            if self._log_paged:
                retained_new = new_lines
            else:
                if len(combined) > LOG_LINES_MAX_RETAINED:
                    self._log_trimmed = True
                combined = combined[-LOG_LINES_MAX_RETAINED:]
                retained_new = new_lines[max(0, len(new_lines) - LOG_LINES_MAX_RETAINED):]
            self._log_lines = combined
            if paint:
                self._write_tail_data(log_pane, retained_new)
        if self._log_mode == "live" and not result.live and not self._log_finished:
            if paint:
                self._clear_log_cursor(log_pane)
            self._log_finished = True
            log_pane.live = False
            if paint:
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

    def _log_at_start(self) -> bool:
        if self._log_trimmed and not self._log_paged:
            return False
        number, offset = self._log_cursor
        return offset <= 0 and number <= self._log_first_session

    def _repaint_log(self) -> None:
        log_pane = self.query_one(LogPane)
        log_pane.quiet_top = True
        log_pane.clear()
        self._log_cursor_active = False
        if not self._log_at_start():
            marker = LogLine(timestamp=None, kind=LogKind.SESSION, text=LOG_EARLIER_NOT_LOADED_MESSAGE)
            log_pane.write_entry(self._render_log_line(marker))
        visible = self._visible_log_lines(self._log_lines)
        live = self._log_mode == "live" and not self._log_finished
        self._paint_log_lines(log_pane, visible, live)
        if self._log_finished and self._log_mode == "live":
            log_pane.write(Text(LOG_FINISHED_MESSAGE, style=COLOURS["cyan"]))
        self.call_after_refresh(self._settle_log_pane)

    def _settle_log_pane(self) -> None:
        log_pane = self.query_one(LogPane)
        log_pane.quiet_top = False
        self._fill_log_pane()

    def _fill_log_pane(self) -> None:
        if self._log_mode in (None, "no-log") or self._log_at_start():
            return
        log_pane = self.query_one(LogPane)
        if not log_pane.display or log_pane.size.height <= 0:
            return
        if log_pane.max_scroll_y == 0:
            self._load_earlier_log()

    def on_log_pane_top_reached(self, message) -> None:
        if self._log_mode in (None, "no-log") or self._log_at_start():
            return
        self._load_earlier_log()

    def _rebuild_log_lines(self) -> None:
        sessions = self._container.store.step_sessions(self._log_target)
        fs = self._container.fs
        worker_log = self._container.worker_log
        lines = []
        for number, start, end in self._log_spans:
            matching = [s for s in sessions if s.n == number]
            if matching:
                session = matching[0]
            elif number == self._log_spans[-1][0] and self._log_path:
                session = StepSession(
                    n=number, log_path=self._log_path, started_at=None, ended_reason=None)
            else:
                continue
            if end is None:
                end = self._log_offset
            if start == 0 and number > 1:
                lines.append(self._separator_for(session, sessions))
            if not fs.exists(session.log_path):
                lines.append(self._not_found_line(session))
                continue
            data, _ = worker_log.read_from_bounded(session.log_path, start, end - start)
            if data:
                lines.extend(LogLineParser().feed(data))
        self._log_lines = lines

    def _load_earlier_log(self) -> None:
        if self._log_at_start():
            return
        log_pane = self.query_one(LogPane)
        if not self._log_paged:
            log_pane.max_lines = None
            self._log_paged = True
            if self._log_trimmed:
                self._rebuild_log_lines()
        sessions = self._container.store.step_sessions(self._log_target)
        number, offset = self._log_cursor
        earlier = ReadEarlierLogUseCase(
            self._container.store, self._container.worker_log, self._container.fs
        ).execute(EarlierLogInput(
            target=self._log_target, session=number, offset=offset, max_bytes=LOG_PAGE_BYTES,
            fallback_path=self._log_path))
        if not earlier.chunks:
            self._log_cursor = (self._log_first_session, 0)
            self._repaint_log()
            return
        self._log_lines = self._take_chunks(earlier.chunks, sessions) + self._log_lines
        previous_scroll = log_pane.scroll_y
        rows_before = len(log_pane.lines) + log_pane._start_line
        self._repaint_log()
        added = len(log_pane.lines) + log_pane._start_line - rows_before
        target = max(0, previous_scroll + added)
        log_pane.auto_scroll = False
        log_pane.scroll_to(y=target, animate=False)
        self.call_after_refresh(lambda: log_pane.scroll_to(y=target, animate=False))

    def action_toggle_thinking(self) -> None:
        if self._active_tab != "log" or self._log_mode == "no-log":
            return
        self._show_thinking = not self._show_thinking
        self._repaint_log()
