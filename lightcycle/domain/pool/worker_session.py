KEEP = "keep"
NUDGE = "nudge"
CLOSE = "close"
MAX_NUDGES = 5


class SessionPolicy:
    def __init__(self):
        self._terminal = False
        self._claimed = False
        self._nudges = 0
        self._rejected = False
        self._session_id = None

    def observe_terminal(self, seen):
        if seen:
            self._terminal = True

    def observe_claimed(self, claimed):
        if claimed:
            self._claimed = True

    def observe_rate_limit(self, event):
        if event is not None and event.is_rejected:
            self._rejected = True

    def observe_session_id(self, session_id):
        if session_id:
            self._session_id = session_id

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

    @property
    def session_id(self):
        return self._session_id
