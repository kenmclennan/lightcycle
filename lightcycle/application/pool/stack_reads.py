from dataclasses import dataclass

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
