import os
from dataclasses import dataclass

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
    def __init__(self, config, git, source, store, scaffold, fs):
        self._config = config
        self._git = git
        self._source = source
        self._store = store
        self._scaffold = scaffold
        self._fs = fs

    def execute(self, name) -> InitWorkflowOriginResponse:
        project_dir = os.path.join(self._config.projects_root(), name)
        if os.path.exists(project_dir):
            raise WorkflowSourceError(
                "%s already exists; choose a different name or remove it first" % project_dir)
        self._scaffold.make_dir(project_dir)
        _write_scaffold(project_dir, name, self._scaffold)
        self._git.init_repo(project_dir, "main")
        self._git.commit_all(project_dir, "scaffold workflow-origin repo")
        add_resp = AddWorkflowSourceUseCase(
            self._source, self._store, self._config, self._fs
        ).execute(url=project_dir, ref="HEAD", name=name)
        self._config.set_personal_origin(name)
        return InitWorkflowOriginResponse(
            project_dir=project_dir, origin=add_resp.origin, sha=add_resp.sha)
