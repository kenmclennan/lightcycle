# the-grid

A workflow-agnostic agent engine fronted by **`tg`**, a single Python CLI that owns
all work and its lifecycle. Work lives in a local SQLite store (hidden behind `tg`)
as tasks chained by dependencies. A run-loop spawns headless `claude -p` workers that
each claim one task, do it, and exit. tmux is optional - every part runs as a
standalone command. You define how you work by composing **workflows** (routing
graphs in `workflows/`) over a library of reusable **steps** (`steps/`); the
engine imposes no spec format or fixed pipeline, and different epics can run
different workflows at once.

The live backlog and roadmap live in the store - run `tg backlog` for open items, `tg status` for the
whole picture.

## Prerequisites

`python3` (3.11+, stdlib only - the engine has no pip deps), `claude` CLI, `git`,
`gh` (authenticated), `pipx` (to install), `glow` (for `bin/grid-spec.sh`).

## Install

the-grid is a pipx-installable package with a `tg` console entry point:

```bash
pipx install git+https://github.com/kenmclennan/the-grid   # tg + the-grid on PATH
tg init                                                     # create ~/.grid (store + config)
```

Everything that is _yours_ lives in **`~/.grid/`** (config, store, logs, worktrees, and
your step/workflow overrides) - separate from the installed engine, so `pipx upgrade`
never touches your data. `~/.grid` is found by default (override with `$GRID_HOME`).

**Upgrading from the old clone-and-run layout?** Run `tg migrate` once - it moves a
legacy `~/.config/the-grid/config` and in-repo `.grid.db` (logs, worktrees) into
`~/.grid`, backing up the store first.

**Developing the engine itself?** Work in a checkout and run it directly
(`python -m the_grid.cli …`, or the `bin/tg` shim) so you dogfood your changes; use
`bin/setup` for the dev environment (`uv` + tests). See [Model](#model) for how the-grid
builds itself.

## Model

- **The engine is workflow-agnostic.** `tg` owns tasks, stories, and the flow, but
  has no opinion on _how you work_ - including your spec format. It only stores a
  spec's path as an artifact; it never parses it. The steps in `steps/` are an
  _example_ workflow (a feature pipeline: coder -> reviewer -> open-pr -> watch-pr,
  then the human steps ready-merge -> cleanup). You define your own way of working
  by composing [workflows](#workflows) over the step library, and whatever a "spec"
  means to them. A spec is whatever your steps understand; hand the Driver one you
  wrote and it flows in as-is.
- **Hierarchy: epic / story / task.** An **epic** is a goal; a **story** is a
  deliverable outcome (one spec -> one branch -> one PR) and **holds the
  artifacts**; a **task** is the work (a flow step under a story, or a standalone
  `tg add` item). `tg file` creates a story + its first task at the step you name.
- **Artifacts live on the story** as a `{type, value, label?}` list (spec, branch,
  pr, ticket, doc, ...). Tasks read their parent story's artifacts - nothing is
  copied between tasks.
- **Steps can declare an artifact contract** (optional) in frontmatter:
  `accepts:` (inputs) and `produces:` (outputs), keyed by artifact type
  (`<type>: required|optional`). A required input gates the work; an optional input
  is read if present but never gates (e.g. the coder accepts `branch: optional`,
  since on a rework pass the branch already exists). `tg` enforces the required
  parts mechanically: a task whose required inputs are absent routes to `for:human`
  instead of running (precondition); `tg done` refuses to close until the required
  outputs are linked (postcondition); `tg file --step` rejects a step whose inputs a
  fresh story can't satisfy; and `tg flow` statically checks the whole pipeline
  composes - every step's required inputs are guaranteed by some upstream producer
  on every path. Presence-only: it checks the story's artifact list, never
  git/GitHub reality. Agents with no contract are unconstrained.
- **Everything is a task.** "build", "review", "open-pr" are tasks chained by
  dependencies; closing one makes its dependents ready. Which task is ready IS the
  stage. The chain is defined by the **workflow graph** (see [Workflows](#workflows)),
  not by the steps: a workflow file names the entry stage, the `outcome -> next-stage`
  edges, and which step file performs each stage. `tg` resolves each task's workflow
  (from its epic) and routes its outcome through that graph - the next performer is the
  step file the target stage maps to (an unowned target is a `for:human` terminal).
  `tg flow` prints the assembled graph.
- **`tg` owns the domain and the processes.** It is the only caller of the store. It
  spawns/tracks workers and runs the loop. No tmux required.
- **Workers are ephemeral and claim their own task.** The loop spawns a role
  (`coder`/`reviewer`/`open-pr`/`watch-pr`); the worker's first act is `tg claim
<role>` (atomic), then it works and exits. A worker that dies before claiming
  leaves nothing stuck. Human steps (`ready-merge`/`cleanup`) are never spawned;
  they surface in `tg inbox`.
- **Three homes: engine / `~/.grid` / projects.** The **engine** is the pipx-installed
  package - code plus the _default_ step/workflow library it ships. **`~/.grid/`** is
  everything that is _yours_: `config`, the store, `logs/`, `worktrees/`, and any
  step/workflow overrides - independent of the engine, so upgrades never touch it (found
  by default, or `$GRID_HOME`). **`projects/`** holds your repos. A step or workflow name
  resolves **`~/.grid/{steps,workflows}` (your overrides) -> the engine default** - drop a
  `~/.grid/steps/coder.md` to change the coder for all your projects, and it survives engine
  upgrades. `tg init` scaffolds the (empty) override dirs. (A per-project `.grid/` file layer
  on top is a planned follow-up.)
- **The config names where your work lives.** `~/.grid/config` (or `$GRID_CONFIG`) names
  `projects` (the dir whose named subdirs are repos; default `~/workspace/projects`) and
  `specs` (base for relative spec paths; default `~/workspace/specs`), plus the global
  `shortcode` (id prefix) and `default-workflow`. `tg init` seeds it; `tg config [--edit]`
  shows or edits it.
- **Per-project `.grid/` (optional).** A project can override the defaults in
  `projects/<name>/.grid/config`: its own `shortcode` (new epic ids under it mint as
  `SHORTCODE-N`, and it's the prefix its specs use) and its own `default-workflow`. It
  may also drop project-local graphs in `.grid/workflows/`. A project with no `.grid/`
  just inherits the global defaults; `tg init <project>` scaffolds the folder.
- **One repo per story, by name.** A story targets exactly one repo, named by a
  `repo` artifact (`tg file <spec> --repo <name>`); the name resolves to
  `projects/<name>`. With no `--repo`, the story targets the engine itself
  (self-dogfood). Cross-repo work is handled by splitting the spec into one story per
  repo, never by a multi-repo workspace.
- **`tg` owns worktree isolation.** On claim, `tg` creates (or reuses) a per-story
  git worktree of the story's repo on branch `grid/<story>` from `origin/main`, under
  `~/.grid/.worktrees/<story>`, and hands the worker its path as the
  claim JSON's `workspace` field (it also auto-links the `branch` artifact). The spec
  lives under `specs`, so the claim JSON also carries `spec_path` (absolute) - workers
  read the spec from there and do all git work in the worktree, never touching the
  primary tree.
- **Labels route work:** `for:<role>` (who acts next), `step:<step>` (flow step),
  `project:`/`goal:`. `for:human` tasks never auto-run; they surface to you.

## Workflows

A **workflow** is a routing graph over the step library - a markdown file in
`workflows/` (or a project's `.grid/workflows/`). The split is deliberate: **steps
are reusable prompts** (`steps/*.md`, carrying only `model` + the optional
`accepts`/`produces` contract), and the **workflow owns all the routing**. Improve a
step once and every workflow benefits; vary the graph without touching the prompts.

A workflow file has up to five sections; only `entry` is required:

```
# Standard - spec -> code -> review -> PR -> merge

entry: build            # the stage a filed story starts at

nodes:                  # stage -> step file (omit when they already match)
  build   coder
  review  reviewer

edges:                  # from-stage  outcome  to-stage
  build     done        review
  review    done        open-pr
  review    rejected    build
  open-pr   done        watch-pr

hooks:                  # engine event -> handling stage (+ value)
  pr_merge       ready-merge  merged
  epic_close     audit
  retro_cadence  audit

signals:                # stage  metric-name  outcome   (retro telemetry)
  review  review_rounds  rejected
```

- A **stage** is a lane (`build`); a **node** maps it to the step file that performs
  it (`coder`). A target with no node/step file (e.g. `conflict-review`) is a
  `for:human` terminal. A stage owned by a step file with no `model` is a human step.
- The engine reacts to a fixed set of **hooks** (`pr_merge`, `pr_close`, `pr_rework`,
  `pr_conflict` (+ `_cap`/`_escalate`), `epic_close`, `retro_cadence`); the graph only
  names which stage handles each. A workflow that omits `pr_*` never opens a PR - e.g.
  a two-line local-only spike: `entry: build` + `build done DONE`.
- `tg flow [--json]` prints and statically checks the resolved graph.

**Selecting a workflow.** Selection lives on the epic and its stories inherit it:

```bash
tg epic "ship the thing"                 # uses the default workflow
tg epic "spike an idea"  --workflow poc  # this epic (and its stories) run poc
tg file spec.md --epic <id>              # inherits the epic's workflow; entry step derived
tg file spec.md --epic <id> --workflow gherkin   # override for one story
```

Resolution order for a task: **story override -> epic workflow -> the project's
`.grid/config` `default-workflow` -> the global `default-workflow`**. Because it's
resolved per task, two epics can run different workflows concurrently.

**Where workflows resolve from.** The engine ships default graphs in its packaged
library; you shadow a name (or add your own) in `~/.grid/workflows/` (a per-project
`.grid/workflows/` layer is a planned follow-up).
A variant step is just another named file the graph points a stage at
(`build -> coder-gherkin`) - no step is ever forked in place.

## Commands

Initialise once with `tg init`, then run the parts in separate terminals.

| Command                                                                              | What it does                                                                        |
| ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| `tg init [<project>]`                                                                | no arg: create `~/.grid` (store + config). `<project>`: scaffold its `.grid/`       |
| `tg config [--edit]`                                                                 | show (or `--edit`) the grid config: projects + specs roots                          |
| `tg migrate`                                                                         | one-time: move a legacy `~/.config` config + in-repo store into `~/.grid`           |
| `tg run [--once]`                                                                    | the agent pool: sweep, then fill up to GRID_MAX_AGENTS workers from the ready queue |
| `tg driver`                                                                          | open the interactive driver `claude` (your seat)                                    |
| `tg status`                                                                          | all buckets: inbox / active / queue / blocked                                       |
| `tg inbox [N]`                                                                       | what needs you now: gates to clear and agents waiting on you                        |
| `tg backlog [N]`                                                                     | backlog items to develop later                                                      |
| `tg active`                                                                          | tasks being worked now                                                              |
| `tg queue [N]`                                                                       | next N upcoming agent tasks                                                         |
| `tg ps [--json]`                                                                     | running workers (role, task, pid, alive)                                            |
| `tg logs <task\|role\|run> [-f]`                                                     | tail a worker's or the loop's log                                                   |
| `tg show <id>`                                                                       | a story (artifacts + child tasks) or a task (+ story artifacts)                     |
| `tg trace <story>`                                                                   | story + its artifacts + child tasks + logs                                          |
| `tg flow [--json]`                                                                   | print + check the assembled flow (stages, routes, contracts, composition)           |
| `tg epic "<objective>" [--workflow <w>]`                                             | open an epic; `--workflow` sets the pipeline its stories run                        |
| `tg file <spec> --epic <id> [--step <s>] [--workflow <w>] [--repo/--project/--goal]` | create a story + first task (step/workflow default to the epic's)                   |
| `tg link <story> <type> <value> [--label]`                                           | attach an artifact to a story                                                       |
| `tg add "<title>"`                                                                   | create a standalone human task (no story/flow)                                      |
| `tg sweep`                                                                           | release orphaned claims (dead worker -> task reclaimable)                           |
| `tg claim <role>`                                                                    | (agents) atomically claim the next task for a role                                  |
| `tg done <id> <outcome>`                                                             | (agents) close with a flow outcome; advances the chain                              |
| `tg block <id> --needs ...`                                                          | (agents) escalate with resume-state -> `for:human`                                  |

## Steps and performers

Every file in `steps/` is a reusable step prompt (routing lives in the
[workflow](#workflows), not here). Its `model:` frontmatter selects who _performs_
it:

- **`model:` present** - an **ephemeral agent**. `tg` spawns a fresh `claude -p`
  (the file body is its system prompt), it does the step and exits. The example
  pipeline uses `opus` for the reviewer, `sonnet` for coder/open-pr/watch-pr.
- **no `model:`** - **you + the Driver**. The step surfaces in `tg inbox`; the file
  body is a Driver skill for helping you do it (`review-plan`, `ready-merge`,
  `cleanup`). These are never spawned.

The Driver is the human's interactive seat and the performer of the human steps -
it composes its instructions from `driver.md` plus those step skills. It is defined
separately in `driver.md` (not under `steps/`, since it is not a single step);
`tg driver` launches it.

## Telemetry / logs

- `logs/workers.json` - role, task (stamped at claim), pid, log path per worker.
  Each `tg sweep` (and so each run-loop tick) prunes dead entries, keeping all live
  workers plus the most recent `GRID_WORKER_HISTORY` dead ones (default 20) so
  `tg logs` can still reach recently finished workers.
- `logs/worker-<role>-<spawnid>.log` - each worker's output (`tg logs` finds it).
- `logs/run.log` - the run-loop's activity.
- Task history gives cycle time, rework, throughput.

## Tests

```bash
bash tests/run.sh          # python3 -m unittest discover
```

## Tear down

`tg run` is foreground - Ctrl-C it. Workers are ephemeral and exit on their own.
If you backgrounded the loop yourself, find it with `tg ps` / kill the `tg run`
process.
