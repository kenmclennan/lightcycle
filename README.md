# lightcycle

A workflow-agnostic agent engine fronted by **`lc`**, a single Python CLI that owns
all work and its lifecycle. Work lives in a local SQLite store (hidden behind `lc`)
as tasks chained by dependencies. A run-loop spawns headless `claude` workers that
each claim one task, do it, and exit. tmux is optional - every part runs as a
standalone command. You define how you work by composing **workflows** (routing
graphs in `workflows/`) over a library of reusable **steps** (`steps/`); the
engine imposes no spec format or fixed pipeline, and different epics can run
different workflows at once.

The name is the double meaning: work rides its **lifecycle** through the engine, and
every task leaves a light-trail - the audit trail of what happened, when, and why.

The live backlog and roadmap live in the store - run `lc backlog` for open items, `lc status` for the
whole picture.

## Prerequisites

- **`python3`** (3.11+, stdlib only - the engine has no pip deps)
- **`claude`** CLI, **signed in to a Claude subscription** (workers bill to your
  subscription, not the API). Run `claude` once and complete login before starting the pool.
- **`git`**, and **`gh`** (authenticated) for the PR steps
- **`pipx`** to install the engine
- optional: **`glow`** (for `bin/lc-spec.sh` spec preview)

## Install

lightcycle is a pipx-installable package with an `lc` console entry point:

```bash
pipx install git+https://github.com/kenmclennan/lightcycle   # lc + lightcycle on PATH
lc init                                                       # create ~/.lightcycle (store + config)
```

Everything that is _yours_ lives in **`~/.lightcycle/`** (config, store, logs, worktrees, and
your step/workflow overrides) - separate from the installed engine, so `pipx upgrade`
never touches your data. `~/.lightcycle` is found by default (override with `$LC_HOME`).

**Upgrading from an older layout?** Run `lc migrate` once - it relocates a legacy
`~/.grid/` (or the even older `~/.config/the-grid/config` + in-repo `.grid.db`) into
`~/.lightcycle`, renaming the store to `store.db` and backing it up first.

## Quickstart

```bash
# 0. one-time prereq: sign in to your Claude subscription
claude            # complete login, then exit

# 1. install + initialise
pipx install git+https://github.com/kenmclennan/lightcycle
lc init                              # creates ~/.lightcycle (store, config, override dirs)
lc config --edit                     # point `projects` + `specs` at your dirs (defaults: ~/workspace/{projects,specs})

# 2. tell lightcycle about a repo you want it to work in
#    (any git repo under your `projects` dir)
lc init myapp                        # scaffold projects/myapp/.lightcycle (shortcode + workflows)

# 3. drive some work in
lc epic "Add a health endpoint"                       # open the goal; prints an epic id, e.g. MYAPP-1
lc file specs/health.md --epic MYAPP-1 --repo myapp   # file a story + its first task from a spec

# 4. run the pool (separate terminal) and watch
lc start                             # the agent loop: claims ready tasks, spawns workers, advances the flow
lc status                            # inbox / active / queue / blocked, all at once
lc driver                            # your interactive seat to shape specs and clear gates
```

`lc start` runs in the foreground and shows the neon banner as it comes online; Ctrl-C
stops it (workers are ephemeral and exit on their own). The pool runs the agent steps;
you drive from `lc driver` and clear the human gates (`review`, `ready-merge`) that
surface in `lc inbox`.

**Developing the engine itself?** Work in a checkout and run it directly
(`python -m lightcycle.cli …`, or the `bin/lc` shim) so you dogfood your changes; use
`bin/setup` for the dev environment (`uv` + tests). See [DEVELOPING.md](DEVELOPING.md).

## Model

- **The engine is workflow-agnostic.** `lc` owns tasks, stories, and the flow, but
  has no opinion on _how you work_ - including your spec format. It only stores a
  spec's path as an artifact; it never parses it. The steps in `steps/` are an
  _example_ workflow (a feature pipeline: coder -> reviewer -> open-pr -> watch-pr,
  then the human steps ready-merge -> cleanup). You define your own way of working
  by composing [workflows](#workflows) over the step library. A spec is whatever your
  steps understand; hand the Driver one you wrote and it flows in as-is.
- **Hierarchy: epic / story / task.** An **epic** is a goal; a **story** is a
  deliverable outcome (one spec -> one branch -> one PR) and **holds the
  artifacts**; a **task** is the work (a flow step under a story, or a standalone
  `lc add` item). `lc file` creates a story + its first task at the step you name.
- **Artifacts live on the story** as a `{type, value, label?}` list (spec, branch,
  pr, ticket, doc, ...). Tasks read their parent story's artifacts - nothing is
  copied between tasks.
- **Steps can declare an artifact contract** (optional) in frontmatter:
  `accepts:` (inputs) and `produces:` (outputs), keyed by artifact type
  (`<type>: required|optional`). A required input gates the work; an optional input
  is read if present but never gates (e.g. the coder accepts `branch: optional`,
  since on a rework pass the branch already exists). `lc` enforces the required
  parts mechanically: a task whose required inputs are absent routes to `for:human`
  instead of running (precondition); `lc done` refuses to close until the required
  outputs are linked (postcondition); `lc file --step` rejects a step whose inputs a
  fresh story can't satisfy; and `lc flow` statically checks the whole pipeline
  composes - every step's required inputs are guaranteed by some upstream producer
  on every path. Presence-only: it checks the story's artifact list, never
  git/GitHub reality. Agents with no contract are unconstrained.
- **Everything is a task.** "build", "review", "open-pr" are tasks chained by
  dependencies; closing one makes its dependents ready. Which task is ready IS the
  stage. The chain is defined by the **workflow graph** (see [Workflows](#workflows)),
  not by the steps: a workflow file names the entry stage, the `outcome -> next-stage`
  edges, and which step file performs each stage. `lc` resolves each task's workflow
  (from its epic) and routes its outcome through that graph - the next performer is the
  step file the target stage maps to (an unowned target is a `for:human` terminal).
  `lc flow` prints the assembled graph.
- **`lc` owns the domain and the processes.** It is the only caller of the store. It
  spawns/tracks workers and runs the loop. No tmux required.
- **Workers are ephemeral and claim their own task.** The loop spawns a role
  (`coder`/`reviewer`/`open-pr`/`watch-pr`); the worker's first act is `lc claim
<role>` (atomic), then it works and exits. A worker that dies before claiming
  leaves nothing stuck. Human steps (`ready-merge`/`cleanup`) are never spawned;
  they surface in `lc inbox`.
- **Three homes: engine / `~/.lightcycle` / projects.** The **engine** is the pipx-installed
  package - code plus the _default_ step/workflow library it ships. **`~/.lightcycle/`** is
  everything that is _yours_: `config`, the store (`store.db`), `logs/`, `.worktrees/`, and any
  step/workflow overrides - independent of the engine, so upgrades never touch it (found
  by default, or `$LC_HOME`). **`projects/`** holds your repos. A step or workflow name
  resolves **`projects/<p>/.lightcycle/{steps,workflows}` -> `~/.lightcycle/{steps,workflows}` -> engine
  default** - drop a `~/.lightcycle/steps/coder.md` to change the coder for all your projects, or a
  `projects/<p>/.lightcycle/workflows/standard.md` to change it for just that project's work; both
  survive engine upgrades. `lc init` scaffolds the (empty) `~/.lightcycle` override dirs.
- **The config names where your work lives.** `~/.lightcycle/config` (or `$LC_CONFIG`) names
  `projects` (the dir whose named subdirs are repos; default `~/workspace/projects`) and
  `specs` (base for relative spec paths; default `~/workspace/specs`), plus the global
  `shortcode` (id prefix) and `default-workflow`. `lc init` seeds it; `lc config [--edit]`
  shows or edits it.
- **Per-project `.lightcycle/` (optional).** A project can override the defaults in
  `projects/<name>/.lightcycle/config`: its own `shortcode` (new epic ids under it mint as
  `SHORTCODE-N`, and it's the prefix its specs use) and its own `default-workflow`. It
  may also drop project-local graphs in `.lightcycle/workflows/`. A project with no
  `.lightcycle/` just inherits the global defaults; `lc init <project>` scaffolds the folder.
- **One repo per story, by name.** A story targets exactly one repo, named by a
  `repo` artifact (`lc file <spec> --repo <name>`); the name resolves to
  `projects/<name>`. Cross-repo work is handled by splitting the spec into one story per
  repo, never by a multi-repo workspace.
- **`lc` owns worktree isolation.** On claim, `lc` creates (or reuses) a per-story
  git worktree of the story's repo on branch `feat/<slug>` (the `branch-prefix` config,
  default `feat`) from `origin/main`, under `~/.lightcycle/.worktrees/<story>`, and hands
  the worker its path as the claim JSON's `workspace` field (it also auto-links the
  `branch` artifact). The spec lives under `specs`, so the claim JSON also carries
  `spec_path` (absolute) - workers read the spec from there and do all git work in the
  worktree, never touching the primary tree.
- **Labels route work:** `for:<role>` (who acts next), `step:<step>` (flow step),
  `project:`/`goal:`. `for:human` tasks never auto-run; they surface to you.

## Workflows

A **workflow** is a routing graph over the step library - a markdown file in
`workflows/` (or a project's `.lightcycle/workflows/`). The split is deliberate: **steps
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
- `lc flow [--json]` prints and statically checks the resolved graph.

**Selecting a workflow.** Selection lives on the epic and its stories inherit it:

```bash
lc epic "ship the thing"                 # uses the default workflow
lc epic "spike an idea"  --workflow poc  # this epic (and its stories) run poc
lc file spec.md --epic <id>              # inherits the epic's workflow; entry step derived
lc file spec.md --epic <id> --workflow gherkin   # override for one story
```

Resolution order for a task: **story override -> epic workflow -> the project's
`.lightcycle/config` `default-workflow` -> the global `default-workflow`**. Because it's
resolved per task, two epics can run different workflows concurrently.

**Where workflows resolve from.** The engine ships default graphs in its packaged
library; you shadow a name (or add your own) in `~/.lightcycle/workflows/` for all projects,
or in `projects/<p>/.lightcycle/workflows/` for just one - resolved project -> `~/.lightcycle` -> default.
A variant step is just another named file the graph points a stage at
(`build -> coder-gherkin`) - no step is ever forked in place.

## Commands

Initialise once with `lc init`, then run the parts in separate terminals.

| Command                                                                              | What it does                                                                              |
| ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| `lc init [<project>]`                                                                | no arg: create `~/.lightcycle` (store + config). `<project>`: scaffold its `.lightcycle/` |
| `lc config [--edit]`                                                                 | show (or `--edit`) the lightcycle config: projects + specs roots                          |
| `lc migrate`                                                                         | one-time: relocate a legacy `~/.grid` or `~/.config` layout into `~/.lightcycle`          |
| `lc start [--once]`                                                                  | the agent pool: sweep, then fill up to LC_MAX_AGENTS workers from the ready queue         |
| `lc driver`                                                                          | open the interactive driver `claude` (your seat)                                          |
| `lc status`                                                                          | all buckets: inbox / active / queue / blocked                                             |
| `lc inbox [N]`                                                                       | what needs you now: gates to clear and agents waiting on you                              |
| `lc backlog [N]`                                                                     | backlog items to develop later                                                            |
| `lc active`                                                                          | tasks being worked now                                                                    |
| `lc queue [N]`                                                                       | next N upcoming agent tasks                                                               |
| `lc ps [--json]`                                                                     | running workers (role, task, pid, alive)                                                  |
| `lc logs <task\|role\|run> [-f]`                                                     | tail a worker's or the loop's log                                                         |
| `lc show <id>`                                                                       | a story (artifacts + child tasks) or a task (+ story artifacts)                           |
| `lc trace <story>`                                                                   | story + its artifacts + child tasks + logs                                                |
| `lc flow [--json]`                                                                   | print + check the assembled flow (stages, routes, contracts, composition)                 |
| `lc epic "<objective>" [--workflow <w>]`                                             | open an epic; `--workflow` sets the pipeline its stories run                              |
| `lc file <spec> --epic <id> [--step <s>] [--workflow <w>] [--repo/--project/--goal]` | create a story + first task (step/workflow default to the epic's)                         |
| `lc link <story> <type> <value> [--label]`                                           | attach an artifact to a story                                                             |
| `lc add "<title>"`                                                                   | create a standalone human task (no story/flow)                                            |
| `lc sweep`                                                                           | release orphaned claims (dead worker -> task reclaimable)                                 |
| `lc claim <role>`                                                                    | (agents) atomically claim the next task for a role                                        |
| `lc done <id> <outcome>`                                                             | (agents) close with a flow outcome; advances the chain                                    |
| `lc block <id> --needs ...`                                                          | (agents) escalate with resume-state -> `for:human`                                        |

## Steps and performers

Every file in `steps/` is a reusable step prompt (routing lives in the
[workflow](#workflows), not here). Its `model:` frontmatter selects who _performs_
it:

- **`model:` present** - an **ephemeral agent**. `lc` spawns a fresh `claude`
  (the file body is its system prompt), it does the step and exits. The example
  pipeline uses `opus` for the reviewer, `sonnet` for coder/open-pr/watch-pr.
- **no `model:`** - **you + the Driver**. The step surfaces in `lc inbox`; the file
  body is a Driver skill for helping you do it (`review-plan`, `ready-merge`,
  `cleanup`). These are never spawned.

The Driver is the human's interactive seat and the performer of the human steps -
it composes its instructions from `driver.md` plus those step skills. It is defined
separately in `driver.md` (not under `steps/`, since it is not a single step);
`lc driver` launches it.

## Telemetry / logs

- `logs/workers.json` - role, task (stamped at claim), pid, log path per worker.
  Each `lc sweep` (and so each run-loop tick) prunes dead entries, keeping all live
  workers plus the most recent `LC_WORKER_HISTORY` dead ones (default 20) so
  `lc logs` can still reach recently finished workers.
- `logs/worker-<role>-<spawnid>.log` - each worker's output (`lc logs` finds it).
- `logs/run.log` - the run-loop's activity.
- Task history gives cycle time, rework, throughput.

## Tests

```bash
bash tests/run.sh          # the full suite via uv + pytest (dev tooling only)
```

## Tear down

`lc start` is foreground - Ctrl-C it. Workers are ephemeral and exit on their own.
If you backgrounded the loop yourself, find it with `lc ps` / kill the `lc start`
process.
