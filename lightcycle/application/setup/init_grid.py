from dataclasses import dataclass

import os

from lightcycle.application.errors import UseCaseError
from lightcycle.application.git_identity import require_git_identity
from lightcycle.config import ConfigError
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE, SPECS_WORKSPACE
from lightcycle.ports.github import ReadFailure
from lightcycle.ports.git import GitReadError
from lightcycle.domain.guidance.conventions import CONVENTIONS_TEXT
from lightcycle.domain.guidance.skeleton import (
    COMMIT_MESSAGE,
    CONVENTIONS_PATH,
    INDEX_PATH,
    INDEX_TEXT,
)

_DEFAULT_SPECS_PATH = "~/workspace/specs"
_DEFAULT_GUIDANCE_PATH = "~/workspace/agent-guidance"


@dataclass(frozen=True)
class InitGridResponse:
    existed: bool
    created: bool
    config_path: str
    guidance_outcome: str = ""
    guidance_path: str = ""
    guidance_refusal: str = ""
    trusted_authors_seeded: str = ""
    trusted_authors_unset_reason: str = ""
    remote_updates: tuple = ()


class InitGridUseCase:
    def __init__(self, store, fs, config, git, github):
        self._store = store
        self._fs = fs
        self._config = config
        self._git = git
        self._github = github

    def execute(self, guidance_path=None) -> InitGridResponse:
        existed = self._fs.store_ready()
        self._store.ensure_store()
        self._fs.ensure_logs_dir()
        created = self._config.ensure_config()
        seeded, unset_reason = self._seed_trusted_authors()
        self._ensure_specs_project()
        remote_updates = self._refresh_remotes()
        refusal = self._identity_refusal_if_creating(guidance_path)
        if refusal:
            outcome = "not created"
            path = self._config.expand_path(guidance_path or _DEFAULT_GUIDANCE_PATH)
        else:
            outcome, path = self._ensure_guidance_project(guidance_path)
        return InitGridResponse(
            existed=existed,
            created=created,
            config_path=self._config.config_path(),
            guidance_outcome=outcome,
            guidance_path=path,
            guidance_refusal=refusal,
            trusted_authors_seeded=seeded,
            trusted_authors_unset_reason=unset_reason,
            remote_updates=remote_updates,
        )

    def _refresh_remotes(self):
        updates = []
        for identity in (GUIDANCE_WORKSPACE, SPECS_WORKSPACE):
            url = self._refreshed_remote(identity)
            if url:
                updates.append("%s: remote updated to %s" % (identity, url))
        return tuple(updates)

    def _refreshed_remote(self, identity):
        registered = self._store.get_project(identity)
        if registered is None or not registered.local_path:
            return ""
        path = self._config.expand_path(registered.local_path)
        if not self._git.is_repo_root(path):
            return ""
        try:
            origin = self._git.remote_url(path)
        except GitReadError:
            return ""
        if not origin or origin == registered.remote:
            return ""
        self._store.add_project(identity, remote=origin)
        return origin

    def _seed_trusted_authors(self):
        try:
            self._config.trusted_authors()
            return "", ""
        except ConfigError:
            pass
        login = self._github.authenticated_login()
        if isinstance(login, ReadFailure):
            return "", login.stderr.strip() or "gh exited %d" % login.returncode
        if not login:
            return "", "gh returned no login"
        self._config.seed_trusted_authors(login)
        return login, ""

    def _identity_refusal_if_creating(self, requested):
        wanted = self._config.expand_path(requested or _DEFAULT_GUIDANCE_PATH)
        if self._store.get_project(GUIDANCE_WORKSPACE) is None and not self._fs.exists(wanted):
            try:
                require_git_identity(self._git, wanted)
            except UseCaseError as e:
                return str(e)
        return ""

    def _ensure_guidance_project(self, requested):
        wanted = self._config.expand_path(requested or _DEFAULT_GUIDANCE_PATH)
        registered = self._store.get_project(GUIDANCE_WORKSPACE)
        if registered is not None:
            if requested and wanted != registered.local_path:
                raise UseCaseError(
                    "guidance repo is already registered at %s, not %s - run "
                    "`lc project rm %s` first to move it"
                    % (registered.local_path, wanted, GUIDANCE_WORKSPACE)
                )
            return "unchanged", registered.local_path
        shortcode = self._guidance_shortcode_checked()
        if not self._fs.exists(wanted):
            self._create_guidance_repo(wanted)
            self._store.add_project(
                GUIDANCE_WORKSPACE, shortcode=shortcode, local_path=wanted, remote=None
            )
            return "created", wanted
        if self._git.is_repo_root(wanted):
            self._store.add_project(
                GUIDANCE_WORKSPACE, shortcode=shortcode, local_path=wanted,
                remote=self._git.remote_url(wanted),
            )
            return "registered", wanted
        raise UseCaseError(
            "guidance repo path %s exists and is not a git repo root - remove it, choose "
            "another with --guidance-path, or run `git init` in it" % wanted
        )

    def _guidance_shortcode_checked(self):
        shortcode = self._config.guidance_shortcode()
        for other in self._store.list_projects():
            if other.identity != GUIDANCE_WORKSPACE and (other.shortcode or "").upper() == shortcode.upper():
                raise UseCaseError(
                    "shortcode '%s' is already held by project %s - change the "
                    "guidance-shortcode config key" % (shortcode, other.identity)
                )
        return shortcode

    def _create_guidance_repo(self, path):
        outcome = self._git.init_repo(path)
        if not outcome.ok:
            raise UseCaseError(self._creation_failure(path, outcome.detail))
        self._fs.write_text(os.path.join(path, INDEX_PATH), INDEX_TEXT)
        self._fs.write_text(os.path.join(path, CONVENTIONS_PATH), CONVENTIONS_TEXT)
        if not self._git.commit_all(path, COMMIT_MESSAGE):
            raise UseCaseError(self._creation_failure(path, "the initial commit failed"))

    def _creation_failure(self, path, detail):
        return "could not create the guidance repo at %s (%s) - remove it and re-run `lc init`" % (
            path,
            detail or "git init failed",
        )

    def _ensure_specs_project(self):
        if self._store.get_project(SPECS_WORKSPACE) is not None:
            return
        legacy = self._config.load_config()
        legacy_path = legacy.get("specs")
        if legacy_path:
            path = self._config.expand_path(legacy_path)
            remote = legacy.get("specs-remote") or None
        else:
            path = self._config.expand_path(_DEFAULT_SPECS_PATH)
            remote = None
        self._store.add_project(SPECS_WORKSPACE, local_path=path, remote=remote)
