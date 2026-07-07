import os
from dataclasses import dataclass
from typing import List

from the_grid.application.errors import UseCaseError


@dataclass(frozen=True)
class InitProjectInput:
    project: str


@dataclass(frozen=True)
class InitProjectResponse:
    grid_dir: str
    created: List[str]


class InitProjectUseCase:
    def __init__(self, config, fs):
        self._config = config
        self._fs = fs

    def _require_global(self):
        if not os.path.exists(self._config.config_path()):
            raise UseCaseError("global config missing - run `tg init` first")
        if not self._fs.store_ready():
            raise UseCaseError("grid store not initialised - run `tg init` first")
        if not os.path.isdir(os.path.join(self._config.library_root(), "workflows")):
            raise UseCaseError("workflows library missing at the grid root - run `tg init` first")

    def execute(self, input: InitProjectInput) -> InitProjectResponse:
        self._require_global()
        proj_dir = os.path.join(self._config.projects_root(), input.project)
        if not os.path.isdir(proj_dir):
            raise UseCaseError(
                "unknown project '%s' under %s" % (input.project, self._config.projects_root())
            )
        grid_dir = os.path.join(proj_dir, ".grid")
        created = []
        workflows = os.path.join(grid_dir, "workflows")
        if not os.path.isdir(workflows):
            os.makedirs(workflows)
            created.append("workflows/")
        cfg = os.path.join(grid_dir, "config")
        if not os.path.exists(cfg):
            shortcode = input.project.rstrip("/").split("/")[-1].upper()
            with open(cfg, "w") as f:
                f.write("shortcode: %s\n" % shortcode)
            created.append("config")
        gitignore = os.path.join(grid_dir, ".gitignore")
        if not os.path.exists(gitignore):
            with open(gitignore, "w") as f:
                f.write("scratch-*.md\n")
            created.append(".gitignore")
        return InitProjectResponse(grid_dir=grid_dir, created=created)
