import os
from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError


@dataclass(frozen=True)
class AddProjectInput:
    identity: str
    shortcode: str = None
    path: str = None


@dataclass(frozen=True)
class AddProjectResponse:
    identity: str
    shortcode: str
    local_path: str
    remote: str
    changed: bool


class AddProjectUseCase:
    def __init__(self, store, git, config, fs):
        self._store = store
        self._git = git
        self._config = config
        self._fs = fs

    def _require_global(self):
        if not os.path.exists(self._config.config_path()):
            raise UseCaseError("global config missing - run `lc init` first")
        if not self._fs.store_ready():
            raise UseCaseError("lightcycle store not initialised - run `lc init` first")

    def execute(self, input: AddProjectInput) -> AddProjectResponse:
        self._require_global()
        if input.identity.count("/") != 1 or not all(input.identity.split("/")):
            raise UseCaseError(
                "project identity must be 'owner/name' (got %r)" % input.identity
            )
        existing = self._store.get_project(input.identity)
        shortcode = (
            input.shortcode or (existing.shortcode if existing else None)
            or input.identity.split("/")[-1].upper()
        )
        remote = self._git.remote_url(input.path) if input.path else None
        local_path = input.path or (existing.local_path if existing else None)
        remote = remote or (existing.remote if existing else None)
        changed = (
            existing is None
            or existing.shortcode != shortcode
            or existing.local_path != local_path
        )
        if changed:
            self._store.add_project(
                input.identity, shortcode=shortcode, local_path=local_path, remote=remote
            )
        return AddProjectResponse(
            identity=input.identity, shortcode=shortcode, local_path=local_path,
            remote=remote, changed=changed,
        )


class ListProjectsUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self):
        return self._store.list_projects()


class RemoveProjectUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, identity):
        try:
            self._store.remove_project(identity)
        except KeyError as e:
            raise UseCaseError(str(e))
