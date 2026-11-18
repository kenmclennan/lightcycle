from dataclasses import dataclass

from lightcycle.domain.pool import stack_shape
from lightcycle.ports.github import ReadFailure


@dataclass(frozen=True)
class StackRead:
    layers: tuple = ()
    dissolved: bool = False
    unread: bool = False


def read_stack(github, url) -> StackRead:
    value = github.stack_view(url)
    if isinstance(value, ReadFailure):
        if "HTTP 404" in (value.stderr or ""):
            return StackRead(dissolved=True)
        return StackRead(unread=True)
    layers = tuple(value)
    if not layers:
        return StackRead(dissolved=True)
    return StackRead(layers=layers)


def rebaseline(store, github, run):
    stack = read_stack(github, run.stack)
    if not stack.layers:
        store.set_stack_seen(run.id, None)
        return
    store.set_stack_seen(
        run.id, stack_shape.encode(stack_shape.record_of(stack.layers, {}, None)))


def record_final_stack(store, run, stack):
    previous = stack_shape.decode(run.stack_seen)
    heads = tuple(dict.fromkeys(
        l.head_ref for l in stack.layers if l.head_ref and l.head_ref != run.branch
    ))
    record = stack_shape.record_of(stack.layers, {}, previous)
    if stack_shape.layer_branches(run) == heads and stack_shape.decode(run.stack_seen) == record:
        return run
    store.set_stack_seen(run.id, stack_shape.encode(record))
    return store.get_run(run.id)
