from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.project_of import project_of, repo_of
from lightcycle.domain.work import Step, node_id_key

_SNIPPET_WINDOW = 40


@dataclass(frozen=True)
class SearchInput:
    text: str


@dataclass(frozen=True)
class SearchMatch:
    node: Step
    project: Optional[str]
    repo: Optional[str]
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


def _fields(node):
    return [(f, getattr(node, f) or "") for f in ("title", "description", "notes")]


def _first_match(node, tokens):
    terms = list(dict.fromkeys(tokens))
    fields = _fields(node)
    haystack = "\n".join(text for _, text in fields).lower()
    if not all(term in haystack for term in terms):
        return None
    phrase = " ".join(tokens)
    for anchor in (phrase, terms[0]):
        for field, text in fields:
            idx = text.lower().find(anchor)
            if idx != -1:
                return field, _snippet(text, idx, len(anchor))
    return None


class SearchUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: SearchInput) -> SearchResponse:
        tokens = input.text.lower().split()
        if not tokens:
            raise UseCaseError("search needs at least one term")
        matches = []
        rows = sorted(self._store.item_texts(), key=lambda r: node_id_key(r.id))
        for row in rows:
            hit = _first_match(row, tokens)
            if hit is None:
                continue
            field, snippet = hit
            node = self._store.get_node(row.id)
            matches.append(SearchMatch(
                node=node, project=project_of(self._store, node), repo=repo_of(self._store, node),
                field=field, snippet=snippet,
            ))
        return SearchResponse(matches=matches)
