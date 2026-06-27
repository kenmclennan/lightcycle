# AGENTS.md - conventions for the-grid

Rules for anyone (human or agent) writing code in this repo. the-grid's generic coder/reviewer steps
are project-agnostic and defer to this file - it is where the-grid's own specifics live.

## Architecture: hexagonal

- `the_grid/core/` - pure domain logic. **Stdlib only, no IO**: no subprocess, filesystem, network,
  env, and no ambient `time`/`uuid`/`random` (pass those in as explicit inputs). Functions take plain
  data and return plain data, so they unit-test in isolation in milliseconds.
- `the_grid/adapters/` - all IO: the bd store, git, the worker spawner, the workers registry, the
  filesystem. The only callers of `bd` / `git` / `subprocess`.
- `the_grid/cli.py` - orchestration only: parse args, gather via adapters, call `core` for the
  decision, apply the effect. **No pure logic lives here** - if it can be a pure function over plain
  data, it belongs in `core/`.

Pure logic stranded in `cli.py` or an adapter is the most common defect here; move it to `core/`.

## Tests

**Run the tests with `bash tests/run.sh`** - it runs the unit suite then the integration suite. This
project uses the Python stdlib `unittest`; there is no pytest and no pip test deps, so do not invoke
`pytest`. Run a subset directly with `python3 -m unittest discover -s tests/unit`.

- `tests/unit/` - fast, isolated tests of `core/` pure functions (no subprocess).
- `tests/test_tg.py` - integration tests exercising the wired `tg` commands via subprocess.
- New pure logic ships with unit tests; a new command ships with an integration test. Get it green
  before `tg done`.

## Style

- Near-zero comments: the "why" goes in commit messages and test names, not inline comments.
- No emdashes anywhere - use hyphens.
- Python modules are `snake_case.py`; step files are `kebab-case.md`.
- Stdlib only - no pip dependencies.

## The agnostic rule (do not break it)

the-grid is a workflow- and project-agnostic engine. Do not bake project-specific assumptions - a
stack, a file layout, a spec format - into the engine, the steps (`steps/*.md`), or `tg`. Those
specifics belong in each target project's own `AGENTS.md` (like this one), which the agnostic steps
read. `tg` provides primitives; the workflow is defined by editable step markdown, not code builtins.

Concretely, `tg` and `core/` must NOT: hardcode a workflow step or role name (e.g. `build`), require
a specific named artifact (e.g. a `spec`), or add a command for one workflow action (e.g. a
`plan-add`). Those are conventions - they live in the step markdown (the agent's prompt), composed
from generic primitives (`tg file`, `tg link`, `tg done`, `--blocked-by`). The test: would this still
make sense for a totally different workflow - a frontend repo, a data pipeline? If not, it does not
belong in the engine. (This rule was learned the hard way: a `tg plan-add` command baked a `build`
step and a required `spec` into `tg`; it was reverted in favour of the planner composing primitives.)
