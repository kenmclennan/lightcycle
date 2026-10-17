import os
from dataclasses import dataclass

from lightcycle.application.git_identity import require_git_identity
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT
from lightcycle.ports.workflow_source import WorkflowSourceError


def _write_scaffold(project_dir, name, scaffold):
    scaffold.write_text(
        os.path.join(project_dir, "source.toml"),
        scaffold.read_template("source.toml") % (name, ENGINE_CONTRACT, name))
    scaffold.write_text(
        os.path.join(project_dir, "CLAUDE.md"),
        scaffold.read_template("CLAUDE.md") % name)
    workflows_dir = os.path.join(project_dir, ".github", "workflows")
    scaffold.make_dir(workflows_dir)
    scaffold.write_text(
        os.path.join(workflows_dir, "simulate.yml"),
        scaffold.read_template("simulate.yml"))
    scaffold.write_text(
        os.path.join(project_dir, "README.md"),
        scaffold.read_template("README.md") % name)


@dataclass(frozen=True)
class InitWorkflowOriginResponse:
    project_dir: str
    origin: str
    sha: str


class InitWorkflowOriginUseCase:
    def __init__(self, config, git, source, store, scaffold, fs, lifecycle):
        self._config = config
        self._git = git
        self._source = source
        self._store = store
        self._scaffold = scaffold
        self._fs = fs
        self._lifecycle = lifecycle

    def execute(self, name) -> InitWorkflowOriginResponse:
        project_dir = os.path.join(self._config.projects_root(), name)
        if self._fs.exists(project_dir):
            raise WorkflowSourceError(
                "%s already exists; choose a different name or remove it first" % project_dir)
        require_git_identity(self._git, project_dir, WorkflowSourceError)
        self._scaffold.make_dir(project_dir)
        _write_scaffold(project_dir, name, self._scaffold)
        self._git.init_repo(project_dir, "main")
        if not self._git.commit_all(project_dir, "scaffold workflow-origin repo"):
            raise WorkflowSourceError(
                "the scaffold commit failed in %s - check git's output there, then remove "
                "the directory and retry" % project_dir)
        add_resp = AddWorkflowSourceUseCase(
            self._source, self._store, self._config, self._fs, self._lifecycle
        ).execute(url=project_dir, ref="HEAD", name=name, writable=True)
        self._config.set_personal_origin(name)
        return InitWorkflowOriginResponse(
            project_dir=project_dir, origin=add_resp.origin, sha=add_resp.sha)
