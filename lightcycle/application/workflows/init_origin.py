import os
from dataclasses import dataclass

from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.errors import WorkflowSourceError
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT

_SOURCE_TOML = """name = "%s"
contract = %d
description = "Personal workflow origin: %s."
"""

_CLAUDE_MD = """# CLAUDE.md - %s

A **workflow origin**: a pullable `lc` source. `source.toml` names it and declares the engine \
contract it targets; `workflows/*.md` are graphs (`entry`/`requires`/`workspace`/`phase`/`nodes`/\
`edges`/`hooks`/`signals`); `steps/*.md` are the agent role prompts a graph's stages reference. \
`lc workflow add`/`upgrade` pulls this repo into an immutable, sha-pinned bundle; each item then \
pins one `<origin>/<name>@<sha>`.

## The self-contained-bundle rule

A workflow in this repo may reference only step files inside this same repo (`steps/*.md`) - \
never a file in another origin, and never the `lc` engine's own `lightcycle/prompts/` (those are \
the engine's own driver/audit prompts, not workflow content). A bundle that reaches outside \
itself is not portable: `lc workflow add` pins a single sha, so an external reference resolves \
against whatever that other location happened to contain at pull time, or nothing at all.

## Building a workflow here

Author with the `lightcycle:author-workflow` skill. If this origin has no workflow yet, \
bootstrap the first one with a generic pipeline (e.g. `spec-driven`) pointed at this repo, the \
same way `lightcycle-workflows` bootstrapped its own `workflow-authoring` workflow. Model a new \
graph and its step prompts on bundles already pulled from the `lightcycle` origin (`spec-driven`, \
`bdd-driven`, `workflow-authoring`) - never on the engine source (`lightcycle/prompts/driver.md` \
and its neighbors are the engine's own prompts, not a workflow template).

## The gate is the simulator, not a test suite

`lc workflow check <origin>/<name>` (static composition) and the `simulate` CI job \
(`.github/workflows/simulate.yml`) are what a PR touching `workflows/*.md` or `steps/*.md` must \
pass. `lc workflow describe <origin>/<name> --mermaid` renders the built graph so a reviewer can \
confirm it matches the design.

## Style

Hyphens not emdashes. Format every file with `npx prettier --write` **except** `workflows/*.md` \
- its `entry`/`requires`/`workspace`/`phase`/`nodes`/`edges`/`hooks`/`signals` blocks are a \
structured graph grammar, not prose, and prettier's markdown formatter reflows them.
"""

_SIMULATE_YML = """name: simulate

on:
  push:
    branches: [main]
  pull_request:

jobs:
  simulate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pipx install git+https://github.com/kenmclennan/lightcycle
      - run: lc workflow add "$GITHUB_WORKSPACE" --name ci-bundle --ref HEAD
      - run: |
          for f in workflows/*.md; do
            name=$(basename "$f" .md)
            lc workflow check "ci-bundle/$name"
            lc workflow simulate "ci-bundle/$name"
          done
"""

_README_MD = """# %s

A personal `lc` workflow origin (see `CLAUDE.md`). No workflow bundles yet - author the first \
one with the `lightcycle:author-workflow` skill.

| Workflow | Gates | Summary |
| -------- | ----- | ------- |
"""


def _write_scaffold(project_dir, name):
    with open(os.path.join(project_dir, "source.toml"), "w") as f:
        f.write(_SOURCE_TOML % (name, ENGINE_CONTRACT, name))
    with open(os.path.join(project_dir, "CLAUDE.md"), "w") as f:
        f.write(_CLAUDE_MD % name)
    workflows_dir = os.path.join(project_dir, ".github", "workflows")
    os.makedirs(workflows_dir)
    with open(os.path.join(workflows_dir, "simulate.yml"), "w") as f:
        f.write(_SIMULATE_YML)
    with open(os.path.join(project_dir, "README.md"), "w") as f:
        f.write(_README_MD % name)


@dataclass(frozen=True)
class InitWorkflowOriginResponse:
    project_dir: str
    origin: str
    sha: str


class InitWorkflowOriginUseCase:
    def __init__(self, config, git, source, store, fs):
        self._config = config
        self._git = git
        self._source = source
        self._store = store
        self._fs = fs

    def execute(self, name) -> InitWorkflowOriginResponse:
        project_dir = os.path.join(self._config.projects_root(), name)
        if os.path.exists(project_dir):
            raise WorkflowSourceError(
                "%s already exists; choose a different name or remove it first" % project_dir)
        os.makedirs(project_dir)
        _write_scaffold(project_dir, name)
        self._git.git(project_dir, "init", "-q", "-b", "main")
        self._git.commit_all(project_dir, "scaffold workflow-origin repo")
        add_resp = AddWorkflowSourceUseCase(self._source, self._store, self._config, self._fs).execute(
            url=project_dir, ref="HEAD", name=name)
        self._config.set_personal_origin(name)
        return InitWorkflowOriginResponse(
            project_dir=project_dir, origin=add_resp.origin, sha=add_resp.sha)
