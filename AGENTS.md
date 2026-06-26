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

- `tests/unit/` - fast, isolated tests of `core/` pure functions (no subprocess).
- `tests/test_tg.py` - integration tests exercising the wired `tg` commands via subprocess.
- New pure logic ships with unit tests; a new command ships with an integration test. Run
  `bash tests/run.sh` (unit then integration) and get it green before `tg done`.

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
