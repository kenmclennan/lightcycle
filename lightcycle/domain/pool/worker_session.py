import json
import re

_TERMINAL = re.compile(r"\blc\s+(?:done|block)\b")

KEEP = "keep"
NUDGE = "nudge"
CLOSE = "close"
MAX_NUDGES = 5


def is_terminal_command(command):
    return bool(command) and _TERMINAL.search(command) is not None


def saw_terminal_command(lines):
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("type") != "assistant":
            continue
        for c in data.get("message", {}).get("content", []) or []:
            if c.get("type") == "tool_use":
                cmd = str((c.get("input") or {}).get("command", ""))
                if is_terminal_command(cmd):
                    return True
    return False


def saw_session_activity(lines):
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") in ("assistant", "result"):
            return True
    return False


class SessionPolicy:
    def __init__(self):
        self._terminal = False
        self._claimed = False
        self._nudges = 0
        self._rejected = False

    def observe_command(self, command):
        if is_terminal_command(command):
            self._terminal = True

    def observe_claimed(self, claimed):
        if claimed:
            self._claimed = True

    def observe_rate_limit(self, event):
        if event is not None and event.is_rejected:
            self._rejected = True

    def on_result(self, has_open_step):
        if self._terminal or self._rejected:
            return CLOSE
        if not has_open_step and not self._claimed:
            return CLOSE
        if self._nudges >= MAX_NUDGES:
            return CLOSE
        self._nudges += 1
        return NUDGE

    @property
    def terminal_seen(self):
        return self._terminal

    @property
    def nudges(self):
        return self._nudges
