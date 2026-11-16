from dataclasses import dataclass
from typing import Optional

from lightcycle.application.pool.stack_reads import read_stack
from lightcycle.domain.pool import stack_shape
from lightcycle.domain.work import parse_timestamp
from lightcycle.ports.github import PrSync, ReadFailure


@dataclass(frozen=True)
class StackConflict:
    position: int
    total: int
    url: str
    sync: PrSync
    behind: bool
    trunk_sync: Optional[PrSync]

    def note(self) -> str:
        where = stack_shape.label(self.position, self.total, self.url)
        if self.behind:
            return "%s is behind its base" % where
        return "%s conflicts" % where


def _fresh(sync, step):
    if isinstance(sync, ReadFailure) or not sync.settled:
        return False
    if sync.read_at is None:
        return True
    opened = parse_timestamp(step.created_at)
    return opened is None or sync.read_at >= opened.timestamp()


def _confirmed(pending, step, layer, sync):
    recorded = pending.get(step.id)
    if recorded is not None and recorded[0] == layer.url:
        if sync.read_at is None or recorded[1] is None or sync.read_at > recorded[1]:
            return True
    pending[step.id] = (layer.url, sync.read_at)
    return False


def scan_stack(
    github, reads, run, step, is_conflicted, pending=None
) -> Optional[StackConflict]:
    pending = {} if pending is None else pending
    read = read_stack(github, run.stack)
    if read.unread or read.dissolved or not read.layers:
        return None
    total = len(read.layers)
    open_layers = [
        (position, layer, reads.read(layer.url))
        for position, layer in enumerate(read.layers, start=1)
        if layer.state == "open"
    ]
    if not open_layers:
        pending.pop(step.id, None)
        return None
    has_merged = len(open_layers) < total
    first_sync = open_layers[0][2]
    trunk_sync = None if isinstance(first_sync, ReadFailure) else first_sync
    for position, layer, sync in open_layers:
        if is_conflicted(sync, step):
            if has_merged and not _confirmed(pending, step, layer, sync):
                return None
            pending.pop(step.id, None)
            return StackConflict(position, total, layer.url, sync, False, trunk_sync)
    pending.pop(step.id, None)
    for position, layer, sync in open_layers:
        if _fresh(sync, step) and sync.behind:
            required = github.requires_up_to_date(sync.base_key)
            if required is True:
                return StackConflict(position, total, layer.url, sync, True, trunk_sync)
            return None
    return None
