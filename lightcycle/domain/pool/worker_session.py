import re

_TERMINAL = re.compile(r"\b(?:lc|tg)\s+(?:done|block)\b")

KEEP = "keep"
NUDGE = "nudge"
CLOSE = "close"


def is_terminal_command(command):
    return bool(command) and _TERMINAL.search(command) is not None


class SessionPolicy:
    def __init__(self):
        self._terminal = False
        self._claimed = False
        self._nudges = 0

    def observe_command(self, command):
        if is_terminal_command(command):
            self._terminal = True

    def observe_claimed(self, claimed):
        if claimed:
            self._claimed = True

    def on_result(self, has_open_step):
        if self._terminal:
            return CLOSE
        if not has_open_step and not self._claimed:
            return CLOSE
        self._nudges += 1
        return NUDGE

    @property
    def terminal_seen(self):
        return self._terminal

    @property
    def nudges(self):
        return self._nudges
