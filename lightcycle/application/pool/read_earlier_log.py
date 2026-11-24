from dataclasses import dataclass
from typing import Optional, Tuple

from lightcycle.domain.work import StepSession


@dataclass(frozen=True)
class EarlierLogInput:
    target: str
    session: int
    offset: int
    max_bytes: int
    fallback_path: Optional[str] = None


@dataclass(frozen=True)
class EarlierChunk:
    session: StepSession
    data: bytes
    exists: bool
    start: int


@dataclass(frozen=True)
class EarlierLog:
    chunks: Tuple[EarlierChunk, ...]


class ReadEarlierLogUseCase:
    def __init__(self, store, worker_log, fs):
        self._store = store
        self._worker_log = worker_log
        self._fs = fs

    def execute(self, input: EarlierLogInput) -> EarlierLog:
        try:
            node = self._store.get_node(input.target)
        except KeyError:
            return EarlierLog(chunks=())
        if node.type != "step":
            return EarlierLog(chunks=())
        sessions = {s.n: s for s in self._store.step_sessions(input.target)}
        if input.session not in sessions and input.fallback_path:
            sessions[input.session] = StepSession(
                n=input.session, log_path=input.fallback_path, started_at=None, ended_reason=None)
        if not sessions:
            return EarlierLog(chunks=())
        first = min(sessions)
        number, offset = input.session, input.offset
        budget = input.max_bytes
        collected = []
        while budget > 0 and not (number <= first and offset <= 0):
            if offset > 0:
                session = sessions.get(number)
                if session is None:
                    break
                if not self._fs.exists(session.log_path):
                    collected.append(EarlierChunk(session, b"", False, 0))
                    offset = 0
                    continue
                data, start = self._worker_log.read_before(session.log_path, offset, budget)
                collected.append(EarlierChunk(session, data, True, start))
                budget -= len(data)
                offset = start
                if start > 0:
                    break
                continue
            number -= 1
            session = sessions.get(number)
            if session is None:
                break
            if not self._fs.exists(session.log_path):
                collected.append(EarlierChunk(session, b"", False, 0))
                continue
            data, eof = self._worker_log.read_tail(session.log_path, budget)
            if not data and eof > 0:
                data, start = self._worker_log.read_before(session.log_path, eof, budget)
            else:
                start = eof - len(data)
            collected.append(EarlierChunk(session, data, True, start))
            budget -= len(data)
            offset = start
            if start > 0:
                break
        collected.reverse()
        return EarlierLog(chunks=tuple(collected))
