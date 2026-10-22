from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TickTiming:
    pid: int
    finished_at: float
    ticks: tuple

    def as_dict(self) -> dict:
        return {
            "pid": self.pid,
            "finished_at": self.finished_at,
            "ticks": [[f, d] for f, d in self.ticks],
        }


@dataclass(frozen=True)
class TickHealth:
    level: str
    median_seconds: Optional[int]
    age_seconds: int


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def tick_timing_from_state(state):
    if not isinstance(state, dict):
        return None
    pid = state.get("pid")
    finished_at = state.get("finished_at")
    ticks = state.get("ticks")
    if not _is_number(pid) or not _is_number(finished_at) or not isinstance(ticks, list):
        return None
    pairs = []
    for t in ticks:
        if not isinstance(t, (list, tuple)) or len(t) != 2:
            return None
        if not _is_number(t[0]) or not _is_number(t[1]):
            return None
        pairs.append((t[0], t[1]))
    return TickTiming(int(pid), finished_at, tuple(pairs))


def tick_timing_started(pid, now):
    return TickTiming(pid, now, ())


def tick_timing_recorded(previous, pid, finished_at, duration, window_seconds):
    kept = previous.ticks if previous is not None and previous.pid == pid else ()
    cutoff = finished_at - window_seconds
    ticks = tuple(t for t in kept + ((finished_at, duration),) if t[0] >= cutoff)
    return TickTiming(pid, finished_at, ticks)


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def tick_health(timing, now, poll_seconds, window_seconds, share_percent, stall_seconds):
    age = max(0, int(now - timing.finished_at))
    window = [d for f, d in timing.ticks if f >= now - window_seconds]
    median = int(_median(window) + 0.5) if window else None
    if now - timing.finished_at > stall_seconds:
        level = "stalled"
    else:
        slow = sum(1 for d in window if d > poll_seconds)
        level = "lagging" if window and slow * 100 > share_percent * len(window) else "healthy"
    return TickHealth(level, median, age)


def tick_age_text(age_seconds):
    if age_seconds < 60:
        return "%ds" % age_seconds
    return "%dm" % (age_seconds // 60)
