from dataclasses import dataclass

import os

from lightcycle.application.errors import UseCaseError
from lightcycle.application.git_identity import require_git_identity
from lightcycle.domain.flow.flow import KNOWLEDGE_WORKSPACE, SPECS_WORKSPACE
from lightcycle.domain.knowledge.skeleton import (
    COMMIT_MESSAGE,
    CONVENTIONS_PATH,
    CONVENTIONS_TEXT,
    INDEX_PATH,
    INDEX_TEXT,
)

_DEFAULT_SPECS_PATH = "~/workspace/specs"
_DEFAULT_KNOWLEDGE_PATH = "~/workspace/knowledge"


@dataclass(frozen=True)
class InitGridResponse:
    existed: bool
    created: bool
    config_path: str
    knowledge_outcome: str = ""
    knowledge_path: str = ""


class InitGridUseCase:
    def __init__(self, store, fs, config, git):
        self._store = store
        self._fs = fs
        self._config = config
        self._git = git

    def execute(self, knowledge_path=None) -> InitGridResponse:
        self._require_identity_if_creating(knowledge_path)
        existed = self._fs.store_ready()
        self._store.ensure_store()
        self._fs.ensure_logs_dir()
        created = self._config.ensure_config()
        self._ensure_specs_project()
        outcome, path = self._ensure_knowledge_project(knowledge_path)
        return InitGridResponse(
            existed=existed,
            created=created,
            config_path=self._config.config_path(),
            knowledge_outcome=outcome,
            knowledge_path=path,
        )

    def _require_identity_if_creating(self, requested):
        wanted = self._config.expand_path(requested or _DEFAULT_KNOWLEDGE_PATH)
        if self._store.get_project(KNOWLEDGE_WORKSPACE) is None and not self._fs.exists(wanted):
            require_git_identity(self._git, wanted)

    def _ensure_knowledge_project(self, requested):
        wanted = self._config.expand_path(requested or _DEFAULT_KNOWLEDGE_PATH)
        registered = self._store.get_project(KNOWLEDGE_WORKSPACE)
        if registered is not None:
            if requested and wanted != registered.local_path:
                raise UseCaseError(
                    "knowledge base is already registered at %s, not %s - run "
                    "`lc project rm %s` first to move it"
                    % (registered.local_path, wanted, KNOWLEDGE_WORKSPACE)
                )
            return "unchanged", registered.local_path
        if not self._fs.exists(wanted):
            self._create_knowledge_repo(wanted)
            self._store.add_project(KNOWLEDGE_WORKSPACE, local_path=wanted, remote=None)
            return "created", wanted
        if self._git.is_repo_root(wanted):
            self._store.add_project(
                KNOWLEDGE_WORKSPACE, local_path=wanted, remote=self._git.remote_url(wanted)
            )
            return "registered", wanted
        raise UseCaseError(
            "knowledge base path %s exists and is not a git repo root - remove it, choose "
            "another with --knowledge-path, or run `git init` in it" % wanted
        )

    def _create_knowledge_repo(self, path):
        outcome = self._git.init_repo(path)
        if not outcome.ok:
            raise UseCaseError(self._creation_failure(path, outcome.detail))
        self._fs.write_text(os.path.join(path, INDEX_PATH), INDEX_TEXT)
        self._fs.write_text(os.path.join(path, CONVENTIONS_PATH), CONVENTIONS_TEXT)
        if not self._git.commit_all(path, COMMIT_MESSAGE):
            raise UseCaseError(self._creation_failure(path, "the initial commit failed"))

    def _creation_failure(self, path, detail):
        return "could not create the knowledge base at %s (%s) - remove it and re-run `lc init`" % (
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
