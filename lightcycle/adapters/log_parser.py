import json
from datetime import datetime

from lightcycle.domain.work.log_line import LogKind, LogLine


def _content_text(content):
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content or ""


def _tool_use_text(block):
    name = block.get("name") or "tool"
    inp = block.get("input") or {}
    if name == "Bash":
        return "$ " + (inp.get("command") or "").strip()
    arg = inp.get("file_path") or inp.get("path") or inp.get("pattern") or ""
    return ("%s %s" % (name, arg)).rstrip()


def _tool_result_text(block):
    text = _content_text(block.get("content"))
    return ("[error] " if block.get("is_error") else "") + text


def _result_event_text(event):
    if event.get("is_error"):
        return "error: %s" % (event.get("terminal_reason") or event.get("stop_reason") or "unknown")
    return "finished (%s)" % (event.get("stop_reason") or "done")


def _api_retry_text(event):
    return "retry %s/%s: %s" % (event.get("attempt"), event.get("max_retries"), event.get("error"))


def _rate_limit_text(event):
    return "rate limit: %s" % (event.get("rate_limit_info") or {}).get("status", "")


def _tool_progress_text(event):
    return "%s running (%ss)" % (event.get("tool_name") or "tool", event.get("elapsed_time_seconds"))


def _background_tasks_text(event):
    tasks = event.get("tasks") or []
    if tasks:
        return "background: %s" % tasks[0].get("description", "")
    return "background tasks changed"


def _task_updated_text(event):
    return "task %s updated" % event.get("task_id", "")


def _task_notification_text(event):
    return event.get("summary") or "task %s" % (event.get("status") or "updated")


_SYSTEM_TEXT = {
    "init": lambda e: "session started",
    "hook_started": lambda e: "hook started: %s" % e.get("hook_name", ""),
    "hook_response": lambda e: "hook: %s -> %s" % (e.get("hook_name", ""), e.get("outcome", "")),
    "task_started": lambda e: "task started: %s" % e.get("description", ""),
}

_PROGRESS_TEXT = {
    "background_tasks_changed": _background_tasks_text,
    "task_updated": _task_updated_text,
    "task_notification": _task_notification_text,
}


class LogLineParser:
    def __init__(self):
        self._buffer = b""
        self._last_timestamp = None

    def feed(self, data: bytes) -> list[LogLine]:
        self._buffer += data
        *complete, self._buffer = self._buffer.split(b"\n")
        lines = []
        for raw in complete:
            lines.extend(self._parse_line(raw))
        return lines

    def _parse_line(self, raw: bytes) -> list[LogLine]:
        text = raw.decode("utf-8", errors="replace")
        if not text.strip():
            return []
        try:
            event = json.loads(text)
        except ValueError:
            return [LogLine(self._last_timestamp, LogKind.UNPARSED, text)]
        return self._dispatch(event, text)

    def _resolve_timestamp(self, event):
        if event.get("type") in ("assistant", "user"):
            raw_ts = event.get("timestamp")
            if raw_ts:
                self._last_timestamp = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        return self._last_timestamp

    def _dispatch(self, event, raw_text) -> list[LogLine]:
        ts = self._resolve_timestamp(event)
        t = event.get("type")
        if t == "assistant":
            return self._assistant_lines(event, ts)
        if t == "user":
            return self._user_lines(event, ts)
        if t == "system":
            return self._system_lines(event, ts, raw_text)
        if t == "result":
            return [LogLine(ts, LogKind.SYSTEM, _result_event_text(event))]
        if t == "rate_limit_event":
            return [LogLine(ts, LogKind.RETRY, _rate_limit_text(event))]
        if t == "tool_progress":
            return [LogLine(ts, LogKind.PROGRESS, _tool_progress_text(event))]
        return [LogLine(ts, LogKind.SYSTEM, raw_text)]

    def _assistant_lines(self, event, ts) -> list[LogLine]:
        lines = []
        for block in event.get("message", {}).get("content") or []:
            kind = block.get("type")
            if kind == "thinking":
                text = (block.get("thinking") or "").strip()
                if text:
                    lines.append(LogLine(ts, LogKind.THINKING, text))
            elif kind == "text":
                text = (block.get("text") or "").strip()
                if text:
                    lines.append(LogLine(ts, LogKind.TEXT, text))
            elif kind == "tool_use":
                lines.append(LogLine(ts, LogKind.TOOL, _tool_use_text(block)))
        return lines

    def _user_lines(self, event, ts) -> list[LogLine]:
        lines = []
        for block in event.get("message", {}).get("content") or []:
            if block.get("type") == "tool_result":
                lines.append(LogLine(ts, LogKind.RESULT, _tool_result_text(block)))
        return lines

    def _system_lines(self, event, ts, raw_text) -> list[LogLine]:
        subtype = event.get("subtype")
        if subtype == "thinking_tokens":
            return []
        if subtype == "api_retry":
            return [LogLine(ts, LogKind.RETRY, _api_retry_text(event))]
        if subtype in _SYSTEM_TEXT:
            return [LogLine(ts, LogKind.SYSTEM, _SYSTEM_TEXT[subtype](event))]
        if subtype in _PROGRESS_TEXT:
            return [LogLine(ts, LogKind.PROGRESS, _PROGRESS_TEXT[subtype](event))]
        return [LogLine(ts, LogKind.SYSTEM, raw_text)]
