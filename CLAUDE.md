# CLAUDE.md - conventions for lightcycle

Rules for anyone (human or agent) writing code in this repo. `claude -p` loads this file, so the
pool's coder/reviewer agents read it automatically - the generic step files stay lightweight (flow
and decisions) and the craft lives here.

## Architecture: hexagonal (DDD)

Dependencies point inward; the domain depends on nothing.

- `lightcycle/domain/` - the typed, IO-free model: entities (`Task`) and value objects (`Status`),
  plus the pure logic (flow assembly, artifact contracts, task projections/buckets, retro signals,
  worklog, workspace). **Stdlib only, no IO**: no subprocess, filesystem, network, env, and no
  ambient `time`/`uuid`/`random` (pass those in as explicit inputs). Unit-tests in milliseconds.
- `lightcycle/ports/` - the abstract interfaces (`StorePort`, `GitPort`, `FsPort`, `WorkersPort`,
  `SpawnerPort`) the application depends on; adapters implement them.
- `lightcycle/application/` - use cases (one action each, grouped by activity: `inspect`, `intake`,
  `flow`, `pool`, `feedback`, `setup`) + cross-cutting services (`FlowService`, `WorktreeService`).
  Depend on ports, not concrete adapters. This is the home for business logic.
- `lightcycle/adapters/` - all IO: the sqlite store (`SqliteStore`), git, the worker spawner, the workers
  registry, the filesystem. The only callers of `sqlite3` / `git` / `subprocess`.
- `lightcycle/config.py` - the single boundary to the environment and the config file (the only reader
  of `os.environ`); required values fail fast. `lightcycle/container.py` - the composition root that
  builds Config + the adapters and injects them.
- `lightcycle/cli.py` - thin: parse args, pick a use case, render the result. **No business logic.**

Business logic stranded in `cli.py` or an adapter is the most common defect here; it belongs in a
use case (`application/`), and any pure rule belongs in `domain/`.

## Tests

**First-time setup: `bin/setup`** - it checks prerequisites (python3, uv, git), installs the dev
environment (`uv sync`), initialises the lightcycle store (`lc init`), and verifies. Idempotent. (The
engine runs on system `python3` with zero runtime deps, so `bin/lc` works without the venv; the venv
is only for the tests.)

**Run the tests with `bash tests/run.sh`** (which is `uv run pytest`). Tests run under **pytest**,
managed by **uv** - this is dev/test tooling, not a runtime dependency (see Style). The existing
tests are stdlib `unittest.TestCase` classes, which pytest runs as-is; new tests may use either
`unittest` style or plain pytest functions. Run a subset with `bash tests/run.sh tests/unit` (the
fast suite) or `bash tests/run.sh -k <name>`.

**Run the full suite before you finish.** The whole suite (`bash tests/run.sh`) runs in seconds now
that the store is in-process `SqliteStore` (unit tier ~2s, feature ~0.25s, and the integration tier
drives the wired `lc` CLI against a temp sqlite store with no external process to `init`). Run it as a
single foreground call and let it block - never background it and poll (a backgrounded process only
reliably gets CPU while your turn is active, so polling starves it), and never reach for `caffeinate` /
`pmset` / host power tweaks to "keep it running" - mutating the host's system state is out of bounds.

- `tests/support/` - test doubles (`FakeStore`, `FakeFs`) and the store-contract base. Helpers, not
  collected as tests.
- `tests/unit/` - fast, isolated tests of `domain/` logic and the application use cases (no subprocess).
- `tests/integration/` - the store contract against a real `SqliteStore` and the tests that drive the
  wired `lc` CLI or exercise genuine git/worktree IO, via subprocess.
- `tests/feature/` - gherkin `.feature` files (the language-agnostic behaviour spec) with pytest-bdd
  step definitions driving the wired cli in-process. The `.feature` files are meant to outlive the
  runner - a future Go/godog port runs them unchanged.

**When to write an integration test (firm - the default is NOT integration).** Almost all behaviour
is tested in-process against `FakeStore`, in milliseconds. Use-case logic, `lc` command behaviour,
and rendering go in `tests/unit/` (or the in-process `call(cmd_x, ...)` + `_fake_setUp` pattern) -
inject a fake, assert the outcome. A new command does **NOT** automatically warrant an integration
test; if its behaviour is expressible against `FakeStore`, that is where it belongs. Write an
integration test ONLY when the thing under test IS the IO a fake cannot stand in for:

1. the store adapter's **contract against a real `SqliteStore`** - one file (`test_store_contract.py`);
   extend it, never scatter ad-hoc store tests across the suite;
2. **a genuine external-IO effect** - that an adapter's IO actually happens (a git/worktree op runs,
   the run-lock locks, `WorkersAdapter.kill` really signals a process). Test the EFFECT in isolation
   against a real disposable target - **never `os.getpid()`**;
3. **read-surface JSON pins** - a `Task`/story field an agent consumes must be proven to survive
   real serialization onto `lc show`/`lc claim` output (see the read-surface bullet below).

**Decision vs effect (the trap that took CI down).** An integration test verifies an adapter
_contract_, real IO, or wiring - it must NEVER verify a _decision_ a fake can make. `SweepUseCase`
deciding _which_ worker to reclaim or kill is pure logic -> **unit** (`FakeWorkers.kill` records the
pid; no real signal). Only _that `os.kill` sends SIGTERM_ is an adapter test, and it targets a real
sacrificial child, never the test's own pid. Driving a decision through its real effect is slow,
duplicative, and self-destructive - a sweep test that registered `os.getpid()` as a worker made the
sweep SIGTERM the whole test run (exit 143), reproducibly, and took down CI for the repo.

If a change does not touch (1)-(3), it ships with a unit test, not an integration test. Get it green
before `lc done`.

- **Any `Task` (or story) field a step reads from `lc show`/`lc claim` JSON needs an integration
  test asserting the field appears in that CLI output** - a unit test on the domain entity alone
  does not prove the field survives `Task.as_dict()` onto the read surface agents actually consume
  (`tests/integration/test_tg.py::TestTaskDTOReadSurface` pins the current set; extend it, don't
  bypass it, when a step starts reading a new field).
- **Never verify against the live lightcycle store.** When checking a `lc` command by hand, point it at a
  throwaway store (`LC_ROOT_OVERRIDE` on a temp dir with its own sqlite store, as the integration
  tests do) - never the live lightcycle store, or you pollute (or worse, mutate) the real backlog. Same rule as
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
- **The engine ships zero runtime dependencies.** Code under `lightcycle/` imports the stdlib only -
  no third-party `import` ever reaches the shipped engine (it keeps the fork portable, the trust
  surface small, and "clone and run" true). **Dev/test tooling is separate and pragmatic**: it lives
  in `pyproject.toml`'s dev group, managed by `uv`, and never imported by `lightcycle/` (currently
  `pytest` + `pytest-bdd`). The hard line is _runtime_, not _tooling_.

## The agnostic rule (do not break it)

lightcycle is a workflow- and project-agnostic engine. Do not bake project-specific assumptions - a
stack, a file layout, a spec format - into the engine, the steps (`steps/*.md`), or `lc`. Those
specifics belong in each target project's own `CLAUDE.md` (like this one), which `claude -p` loads
for the agnostic steps. `lc` provides primitives; the workflow is defined by editable step markdown,
not code builtins.

Concretely, `lc` and `domain/` must NOT: hardcode a workflow step or role name (e.g. `build`), require
a specific named artifact (e.g. a `spec`), or add a command for one workflow action (e.g. a
`plan-add`). Those are conventions - they live in the step markdown (the agent's prompt), composed
from generic primitives (`lc file`, `lc link`, `lc done`, `--blocked-by`). The test: would this still
make sense for a totally different workflow - a frontend repo, a data pipeline? If not, it does not
belong in the engine. (This rule was learned the hard way: a `lc plan-add` command baked a `build`
step and a required `spec` into `lc`; it was reverted in favour of the planner composing primitives.)
