import os
from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.config import ConfigError
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE
from lightcycle.domain.work import ProjectIdentity, parse_facets
from lightcycle.domain.work.project_identity import reserved_shortcode_reason
from lightcycle.ports.git import GitReadError
from lightcycle.ports.store import ProjectNotRegisteredError, ProjectResolutionError


@dataclass(frozen=True)
class AddProjectInput:
    identity: str
    shortcode: str = None
    path: str = None
    facets: str = None


@dataclass(frozen=True)
class AddProjectResponse:
    identity: str
    shortcode: str
    local_path: str
    remote: str
    changed: bool
    facets: tuple = ()


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
        try:
            identity = ProjectIdentity.parse(input.identity)
        except ValueError as e:
            raise UseCaseError(str(e))
        facets = _parse(input.facets)
        existing = self._store.get_project(input.identity)
        shortcode = (
            input.shortcode or (existing.shortcode if existing else None)
            or identity.default_shortcode
        )
        reason = reserved_shortcode_reason(
            shortcode, _guidance_shortcode_for(self._config, input.identity)
        )
        if reason and shortcode != (existing.shortcode if existing else None):
            raise UseCaseError(reason)
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
            or (facets is not None and facets != existing.facets)
        )
        if changed:
            self._store.add_project(
                input.identity, shortcode=shortcode, local_path=local_path, remote=remote,
                facets=facets,
            )
        current = facets if facets is not None else (existing.facets if existing else ())
        return AddProjectResponse(
            identity=input.identity, shortcode=shortcode, local_path=local_path,
            remote=remote, changed=changed, facets=current,
        )


def _guidance_shortcode_for(config, identity):
    if identity == GUIDANCE_WORKSPACE:
        return None
    try:
        return config.guidance_shortcode()
    except ConfigError:
        return None


def _parse(text):
    if text is None:
        return None
    try:
        return parse_facets(text)
    except ValueError as e:
        raise UseCaseError(str(e))


@dataclass(frozen=True)
class SetProjectResponse:
    identity: str
    facets: tuple
    changed: bool
    shortcode: str = None
    shortcode_changed: bool = False
    facets_given: bool = False


class SetProjectUseCase:
    def __init__(self, store, config):
        self._store = store
        self._config = config

    def execute(self, identity, facets_text=None, shortcode=None):
        if facets_text is None and shortcode is None:
            raise UseCaseError(
                'nothing to set - pass --facets a,b,c (or --facets "" to clear them) '
                "or --shortcode X"
            )
        facets = _parse(facets_text) if facets_text is not None else None
        existing = self._store.get_project(identity)
        if existing is None:
            registered = [p.identity for p in self._store.list_projects()]
            if registered:
                raise UseCaseError(
                    "project '%s' is not registered - registered: %s"
                    % (identity, ", ".join(registered))
                )
            raise UseCaseError(
                "project '%s' is not registered - none registered yet; run "
                "`lc project add <owner/name> --path <dir> --facets a,b,c`" % identity
            )
        shortcode_changed = False
        if shortcode is not None:
            shortcode_changed = self._check_shortcode(existing, shortcode)
        changed = facets is not None and existing.facets != facets
        if shortcode_changed and changed:
            self._store.add_project(identity, shortcode=shortcode, facets=facets)
        elif shortcode_changed:
            self._store.add_project(identity, shortcode=shortcode)
        elif changed:
            self._store.add_project(identity, facets=facets)
        return SetProjectResponse(
            identity=identity,
            facets=facets if facets is not None else existing.facets,
            changed=changed,
            shortcode=shortcode if shortcode is not None else existing.shortcode,
            shortcode_changed=shortcode_changed,
            facets_given=facets is not None,
        )

    def _check_shortcode(self, existing, shortcode):
        if not shortcode.strip():
            raise UseCaseError("shortcode must not be empty")
        reason = reserved_shortcode_reason(
            shortcode, _guidance_shortcode_for(self._config, existing.identity)
        )
        if reason:
            raise UseCaseError(reason)
        for other in self._store.list_projects():
            if (
                other.identity != existing.identity
                and (other.shortcode or "").upper() == shortcode.upper()
            ):
                raise UseCaseError(
                    "shortcode '%s' is already held by project %s" % (shortcode, other.identity)
                )
        if existing.shortcode == shortcode:
            return False
        if existing.shortcode:
            prefix = existing.shortcode + "-"
            carried = sum(
                1 for item in self._store.all_items_including_done() if item.id.startswith(prefix)
            )
            if carried:
                raise UseCaseError(
                    "project %s keeps shortcode %s: ids are immutable and %d item(s) carry the "
                    "%s prefix" % (existing.identity, existing.shortcode, carried, prefix)
                )
        return True


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
            raise ProjectNotRegisteredError(
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
        return [p for p in rows if ProjectIdentity.short_name(p.identity) == ref]
