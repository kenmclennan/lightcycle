from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work.resolve_backlog import link_resolves
from lightcycle.application.work.resolve_shortcode import resolve_shortcode


@dataclass(frozen=True)
class OpenThemeInput:
    objective: str
    backlog: Optional[List[str]] = None
    project: Optional[str] = None
    workflow: Optional[str] = None
    repo: Optional[str] = None


@dataclass(frozen=True)
class OpenThemeResponse:
    theme: str
    shortcode: str
    shortcode_defaulted: bool


class OpenThemeUseCase:
    def __init__(self, store, config):
        self._store = store
        self._config = config

    def execute(self, input: OpenThemeInput) -> OpenThemeResponse:
        resolved = resolve_shortcode(self._store, self._config, input.project)
        theme = self._store.create_theme(
            input.objective, project=input.project, workflow=input.workflow,
            shortcode=resolved.value,
        )
        if input.repo:
            self._store.add_artifact(theme, "repo", input.repo)
        if input.backlog:
            link_resolves(self._store, theme, input.backlog)
        return OpenThemeResponse(
            theme=theme, shortcode=resolved.value, shortcode_defaulted=resolved.defaulted)
