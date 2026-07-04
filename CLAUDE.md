# CLAUDE.md - conventions for the-grid

Rules for anyone (human or agent) writing code in this repo. `claude -p` loads this file, so the
pool's coder/reviewer agents read it automatically - the generic step files stay lightweight (flow
and decisions) and the craft lives here.

## Architecture: hexagonal (DDD)

Dependencies point inward; the domain depends on nothing.

- `the_grid/domain/` - the typed, IO-free model: entities (`Task`) and value objects (`Status`),
  plus the pure logic (flow assembly, artifact contracts, task projections/buckets, retro signals,
  worklog, workspace). **Stdlib only, no IO**: no subprocess, filesystem, network, env, and no
  ambient `time`/`uuid`/`random` (pass those in as explicit inputs). Unit-tests in milliseconds.
- `the_grid/ports/` - the abstract interfaces (`StorePort`, `GitPort`, `FsPort`, `WorkersPort`,
  `SpawnerPort`) the application depends on; adapters implement them.
- `the_grid/application/` - use cases (one action each, grouped by activity: `inspect`, `intake`,
  `flow`, `pool`, `feedback`, `setup`) + cross-cutting services (`FlowService`, `WorktreeService`).
  Depend on ports, not concrete adapters. This is the home for business logic.
- `the_grid/adapters/` - all IO: the bd store (`BdStore`), git, the worker spawner, the workers
  registry, the filesystem. The only callers of `bd` / `git` / `subprocess`.
- `the_grid/config.py` - the single boundary to the environment and the config file (the only reader
  of `os.environ`); required values fail fast. `the_grid/container.py` - the composition root that
  builds Config + the adapters and injects them.
- `the_grid/cli.py` - thin: parse args, pick a use case, render the result. **No business logic.**

Business logic stranded in `cli.py` or an adapter is the most common defect here; it belongs in a
use case (`application/`), and any pure rule belongs in `domain/`.

## Tests

**First-time setup: `bin/setup`** - it checks prerequisites (python3, uv, bd, git), installs the dev
environment (`uv sync`), initialises the grid store (`tg init`), and verifies. Idempotent. (The
engine runs on system `python3` with zero runtime deps, so `bin/tg` works without the venv; the venv
is only for the tests.)

**Run the tests with `bash tests/run.sh`** (which is `uv run pytest`). Tests run under **pytest**,
managed by **uv** - this is dev/test tooling, not a runtime dependency (see Style). The existing
tests are stdlib `unittest.TestCase` classes, which pytest runs as-is; new tests may use either
`unittest` style or plain pytest functions. Run a subset with `bash tests/run.sh tests/unit` (the
fast suite) or `bash tests/run.sh -k <name>`.

**Coders verify on the fast tier; the full suite is the reviewer's gate.** The unit tier
(`bash tests/run.sh tests/unit`) is ~2s (485 tests); feature is ~0.25s. The integration tier shells
out to real `bd` per operation and takes **minutes** - the only slow tier. As a **coder**, verify
with the unit tier plus `-k <name>` on any integration test your change touches - fast, foreground,
and it never trips the harness. Do **NOT** run the full `bash tests/run.sh` as a coder: it takes
minutes, and the harness **auto-backgrounds any command over ~2 min**. An ephemeral worker that ends
its turn while a command runs in the background **abandons its task** - it is reclaimed by the sweep
and restarted from scratch, losing all its work. The **reviewer** runs the full suite as the gate.

When you must run a command that may exceed ~2 min (the reviewer's full-suite gate), pass an explicit
high `timeout` to the Bash tool (up to 600000 ms) so it runs to completion in the **foreground**;
never let it auto-background and then end your turn waiting on it. Do not use the shell `timeout`
command to bound runs - it is not on macOS (it is `gtimeout`, usually absent); use the Bash tool's
own `timeout` parameter.

- `tests/support/` - test doubles (`FakeStore`, `FakeFs`) and the store-contract base. Helpers, not
  collected as tests.
- `tests/unit/` - fast, isolated tests of `domain/` logic and the application use cases (no subprocess).
- `tests/integration/` - the store contract against real `bd` and the tests that exercise genuine
  IO, via subprocess/real backend (slow).
- `tests/feature/` - gherkin `.feature` files (the language-agnostic behaviour spec) with pytest-bdd
  step definitions driving the wired cli in-process. The `.feature` files are meant to outlive the
  runner - a future Go/godog port runs them unchanged.

**When to write an integration test (firm - the default is NOT integration).** Almost all behaviour
is tested in-process against `FakeStore`, in milliseconds. Use-case logic, `tg` command behaviour,
and rendering go in `tests/unit/` (or the in-process `call(cmd_x, ...)` + `_fake_setUp` pattern) -
inject a fake, assert the outcome. A new command does **NOT** automatically warrant an integration
test; if its behaviour is expressible against `FakeStore`, that is where it belongs. Write a slow
integration test ONLY when the thing under test IS the IO a fake cannot stand in for:

1. the store adapter's **contract against real `bd`** - one file (`test_store_contract.py`); extend
   it, never scatter ad-hoc bd tests across the suite;
2. **genuine external IO** - git/worktree operations, process/worker spawning, the run-lock, the
   filesystem;
3. **read-surface JSON pins** - a `Task`/story field an agent consumes must be proven to survive
   real serialization onto `tg show`/`tg claim` output (see the read-surface bullet below).

If a change does not touch (1)-(3), it ships with a unit test, not an integration test. Any
integration test that must touch `bd` **shares one store per class** (`setUpClass`, never a fresh
`bd init` per `setUp` - `bd init` is ~1.6s and a per-method init is the tier's dominant cost). Get
it green before `tg done`.

- **Any `Task` (or story) field a step reads from `tg show`/`tg claim` JSON needs an integration
  test asserting the field appears in that CLI output** - a unit test on the domain entity alone
  does not prove the field survives `Task.as_dict()` onto the read surface agents actually consume
  (`tests/integration/test_tg.py::TestTaskDTOReadSurface` pins the current set; extend it, don't
  bypass it, when a step starts reading a new field).
- **Never verify against the live grid store.** When checking a `tg` command by hand, point it at a
  throwaway store (`GRID_ROOT_OVERRIDE` on a temp dir with its own `bd init`, as the integration
  tests do) - never the live grid, or you pollute (or worse, mutate) the real backlog. Same rule as
  the tests: isolate the store.

## Preferred skills (invoke before the work)

The craft is carried by skills, not by fattening the step files. Invoke them:

- **Designing a spec**: `brainstorming`, then `writing-plans`. Question the approach and find the
  minimal solution before committing mechanism. Do NOT add structure (flags, counts, categories,
  parsers) by analogy to an existing pattern - justify each piece against the actual need, or leave
  it out. The feedback/data is usually the value; an LLM can read freeform text without codified
  scaffolding.
- **Building**: `test-driven-development` - new behaviour ships with a failing test first.
- **Reviewing**: `requesting-code-review` / `receiving-code-review`, and verify the work meets its
  spec's acceptance criteria (run it, do not infer).

Two craft checks that belong here, not in the step prompts: **no broken windows** (no failing or
skipped tests, dead code, or leftover TODOs) and **names that age well** (never bake a deprecated
concept into a durable identifier).

## Style

- No comments and no docstrings: zero `#` comments and zero docstrings anywhere. The "why" goes in commit messages and test names.
- No emdashes anywhere - use hyphens.
- Python modules are `snake_case.py`; step files are `kebab-case.md`.
- **The engine ships zero runtime dependencies.** Code under `the_grid/` imports the stdlib only -
  no third-party `import` ever reaches the shipped engine (it keeps the fork portable, the trust
  surface small, and "clone and run" true). **Dev/test tooling is separate and pragmatic**: it lives
  in `pyproject.toml`'s dev group, managed by `uv`, and never imported by `the_grid/` (currently
  `pytest` + `pytest-bdd`). The hard line is _runtime_, not _tooling_.

## The agnostic rule (do not break it)

the-grid is a workflow- and project-agnostic engine. Do not bake project-specific assumptions - a
stack, a file layout, a spec format - into the engine, the steps (`steps/*.md`), or `tg`. Those
specifics belong in each target project's own `CLAUDE.md` (like this one), which `claude -p` loads
for the agnostic steps. `tg` provides primitives; the workflow is defined by editable step markdown,
not code builtins.

Concretely, `tg` and `domain/` must NOT: hardcode a workflow step or role name (e.g. `build`), require
a specific named artifact (e.g. a `spec`), or add a command for one workflow action (e.g. a
`plan-add`). Those are conventions - they live in the step markdown (the agent's prompt), composed
from generic primitives (`tg file`, `tg link`, `tg done`, `--blocked-by`). The test: would this still
make sense for a totally different workflow - a frontend repo, a data pipeline? If not, it does not
belong in the engine. (This rule was learned the hard way: a `tg plan-add` command baked a `build`
step and a required `spec` into `tg`; it was reverted in favour of the planner composing primitives.)
