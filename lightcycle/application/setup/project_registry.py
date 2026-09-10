import os
from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.ports.git import GitReadError
from lightcycle.ports.store import ProjectResolutionError


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
        remote = None
        if input.path:
            try:
                remote = self._git.remote_url(input.path)
            except GitReadError:
                remote = None
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


class ProjectRegistry:
    def __init__(self, store):
        self._store = store

    def find(self, ref):
        matches = self._match(ref)
        if not matches:
            raise ProjectResolutionError(
                "project '%s' is not registered - run `lc project add <owner/name> --path <dir>`"
                % ref
            )
        if len(matches) > 1:
            raise ProjectResolutionError(
                "project name '%s' is ambiguous - matches %s; use the full owner/name identity"
                % (ref, ", ".join(p.identity for p in matches))
            )
        return matches[0]

    def resolve_path(self, ref):
        if os.path.isabs(ref):
            return ref
        project = self.find(ref)
        if not project.local_path:
            raise ProjectResolutionError(
                "project '%s' is registered but has no local checkout - activate the item to "
                "clone it automatically, or run `lc project add %s --path <dir>` to point at an "
                "existing one" % (project.identity, project.identity)
            )
        return project.local_path

    def _match(self, ref):
        rows = self._store.list_projects()
        if "/" in ref:
            return [p for p in rows if p.identity == ref]
        return [p for p in rows if p.identity.rsplit("/", 1)[-1] == ref]
