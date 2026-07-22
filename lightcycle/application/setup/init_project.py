import os
from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError


@dataclass(frozen=True)
class InitProjectInput:
    project: str
    shortcode: str = None


@dataclass(frozen=True)
class InitProjectResponse:
    project: str
    shortcode: str
    changed: bool


class InitProjectUseCase:
    def __init__(self, config, fs):
        self._config = config
        self._fs = fs

    def _require_global(self):
        if not os.path.exists(self._config.config_path()):
            raise UseCaseError("global config missing - run `lc init` first")
        if not self._fs.store_ready():
            raise UseCaseError("lightcycle store not initialised - run `lc init` first")

    def execute(self, input: InitProjectInput) -> InitProjectResponse:
        self._require_global()
        existing = self._config.project_shortcodes().get(input.project)
        shortcode = (
            input.shortcode or existing
            or input.project.rstrip("/").split("/")[-1].upper()
        )
        changed = shortcode != existing
        if changed:
            self._config.set_project_shortcode(input.project, shortcode)
        return InitProjectResponse(project=input.project, shortcode=shortcode, changed=changed)
