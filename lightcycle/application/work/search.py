from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work.project_of import project_of
from lightcycle.domain.work import Node

_SNIPPET_WINDOW = 40


@dataclass(frozen=True)
class SearchInput:
    text: str


@dataclass(frozen=True)
class SearchMatch:
    node: Node
    project: Optional[str]
    field: str
    snippet: str


@dataclass(frozen=True)
class SearchResponse:
    matches: List[SearchMatch]


def _snippet(text, idx, needle_len):
    start = max(0, idx - _SNIPPET_WINDOW)
    end = min(len(text), idx + needle_len + _SNIPPET_WINDOW)
    return "%s%s%s" % (
        "..." if start > 0 else "",
        text[start:end],
        "..." if end < len(text) else "",
    )


def _first_match(node, needle):
    for field in ("title", "description", "notes"):
        text = getattr(node, field) or ""
        idx = text.lower().find(needle)
        if idx != -1:
            return field, _snippet(text, idx, len(needle))
    return None


class SearchUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: SearchInput) -> SearchResponse:
        needle = input.text.lower()
        matches = []
        items = sorted(
            (n for n in self._store.all_nodes_including_done() if n.type == "item"),
            key=lambda n: n.id,
        )
        for node in items:
            hit = _first_match(node, needle)
            if hit is None:
                continue
            field, snippet = hit
            matches.append(SearchMatch(
                node=node, project=project_of(self._store, node), field=field, snippet=snippet,
            ))
        return SearchResponse(matches=matches)
