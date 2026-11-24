from dataclasses import dataclass
from typing import List

from lightcycle.domain.work import StepSession


@dataclass(frozen=True)
class TailSessionsInput:
    target: str
    max_bytes: int


@dataclass(frozen=True)
class SessionTail:
    session: StepSession
    data: bytes
    exists: bool


class TailSessionsUseCase:
    def __init__(self, store, worker_log, fs):
        self._store = store
        self._worker_log = worker_log
        self._fs = fs

    def execute(self, input: TailSessionsInput) -> List[SessionTail]:
        try:
            node = self._store.get_node(input.target)
        except KeyError:
            return []
        if node.type != "step":
            return []
        sessions = self._store.step_sessions(input.target)
        tails = []
        for session in sessions[:-1]:
            exists = self._fs.exists(session.log_path)
            data = b""
            if exists:
                data, _offset = self._worker_log.read_tail(session.log_path, input.max_bytes)
            tails.append(SessionTail(session=session, data=data, exists=exists))
        return tails
