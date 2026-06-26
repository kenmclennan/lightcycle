# the-grid

A workflow-agnostic agent engine fronted by **`tg`**, a single Python CLI that owns
all work and its lifecycle. Work lives in **beads** (`bd`, hidden behind `tg`) as
tasks chained by dependencies. A run-loop spawns headless `claude -p` workers that
each claim one task, do it, and exit. tmux is optional - every part runs as a
standalone command. You define how you work by editing the steps in `steps/`; the
engine imposes no spec format or fixed pipeline.

See `BACKLOG.md` for the roadmap and known gaps.

## Prerequisites

`python3` (3.9+, stdlib only - no pip deps), `bd` (beads), `claude` CLI, `git`,
`gh` (authenticated), `glow` (for `bin/grid-spec.sh`).

## Install

```bash
ln -sf "$PWD/bin/tg" ~/.local/bin/tg          # tg on PATH
ln -sf "$PWD/bin/tg" ~/.local/bin/the-grid    # long alias
```

`tg` resolves the project root from its own (symlinked) location, so it works from
any directory.

## Model

- **The engine is workflow-agnostic.** `tg` owns tasks, stories, and the flow, but
  has no opinion on _how you work_ - including your spec format. It only stores a
  spec's path as an artifact; it never parses it. The steps in `steps/` are an
  _example_ workflow (a feature pipeline: coder -> reviewer -> open-pr -> watch-pr,
  then the human steps ready-merge -> cleanup). You define your own way of working
  by editing and creating steps - their routes,
  and whatever a "spec" means to them. A spec is whatever your steps
  understand; hand the Driver one you wrote and it flows in as-is.
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
  stage. The chain is defined by the steps themselves: each step declares its
  `step` name and `routes:` (`outcome -> next-step`) in frontmatter, and `tg`
  assembles the flow from them - the next performer is derived from whichever step
  file owns the next step (an unowned target is a `for:human` terminal). `tg flow`
  prints the assembled graph.
- **`tg` owns the domain and the processes.** It is the only caller of `bd`. It
  spawns/tracks workers and runs the loop. No tmux required.
- **Workers are ephemeral and claim their own task.** The loop spawns a role
  (`coder`/`reviewer`/`open-pr`/`watch-pr`); the worker's first act is `tg claim
<role>` (atomic), then it works and exits. A worker that dies before claiming
  leaves nothing stuck. Human steps (`ready-merge`/`cleanup`) are never spawned;
  they surface in `tg mine`.
- **HOME config: where your work lives.** A single config file (`$GRID_CONFIG`, else
  `$XDG_CONFIG_HOME`/`~/.config`/`the-grid/config`) names two roots: `projects` (the
  dir whose named subdirs are repos; default `~/workspace/projects`) and `specs` (the
  base for relative spec paths; default `~/workspace/specs`). `tg init` seeds it;
  `tg config [--edit]` shows or edits it. The engine's own data (tg, steps, store,
  logs) stays at the grid root - the config is only about _your_ work's location.
- **One repo per story, by name.** A story targets exactly one repo, named by a
  `repo` artifact (`tg file <spec> --repo <name>`); the name resolves to
  `projects/<name>`. With no `--repo`, the story targets the engine itself
  (self-dogfood). Cross-repo work is handled by splitting the spec into one story per
  repo, never by a multi-repo workspace.
- **`tg` owns worktree isolation.** On claim, `tg` creates (or reuses) a per-story
  git worktree of the story's repo on branch `grid/<story>` from `origin/main`, under
  the engine's gitignored `.worktrees/<story>`, and hands the worker its path as the
  claim JSON's `workspace` field (it also auto-links the `branch` artifact). The spec
  lives under `specs`, so the claim JSON also carries `spec_path` (absolute) - workers
  read the spec from there and do all git work in the worktree, never touching the
  primary tree.
- **Labels route work:** `for:<role>` (who acts next), `step:<step>` (flow step),
  `project:`/`goal:`. `for:human` tasks never auto-run; they surface to you.

## Commands

Initialise once with `tg init`, then run the parts in separate terminals.

| Command                                                         | What it does                                                                        |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `tg init`                                                       | one-time: create the grid store and seed the HOME config                            |
| `tg config [--edit]`                                            | show (or `--edit`) the grid config: projects + specs roots                          |
| `tg run [--once]`                                               | the agent pool: sweep, then fill up to GRID_MAX_AGENTS workers from the ready queue |
| `tg driver`                                                     | open the interactive driver `claude` (your seat)                                    |
| `tg status`                                                     | all buckets: mine / active / queue / blocked                                        |
| `tg mine`                                                       | tasks that need you (`for:human`)                                                   |
| `tg active`                                                     | tasks being worked now                                                              |
| `tg queue [N]`                                                  | next N upcoming agent tasks                                                         |
| `tg ps [--json]`                                                | running workers (role, bead, pid, alive)                                            |
| `tg logs <task\|role\|run> [-f]`                                | tail a worker's or the loop's log                                                   |
| `tg show <id>`                                                  | a story (artifacts + child tasks) or a task (+ story artifacts)                     |
| `tg trace <story>`                                              | story + its artifacts + child tasks + logs                                          |
| `tg flow [--json]`                                              | print + check the assembled flow (steps, routes, contracts, composition)            |
| `tg file <spec> --step <step> [--repo/--epic/--project/--goal]` | create a story (spec + one repo) + first task at `<step>`                           |
| `tg link <story> <type> <value> [--label]`                      | attach an artifact to a story                                                       |
| `tg add "<title>"`                                              | create a standalone human task (no story/flow)                                      |
| `tg sweep`                                                      | release orphaned claims (dead worker -> task reclaimable)                           |
| `tg claim <role>`                                               | (agents) atomically claim the next task for a role                                  |
| `tg done <id> <outcome>`                                        | (agents) close with a flow outcome; advances the chain                              |
| `tg block <id> --needs ...`                                     | (agents) escalate with resume-state -> `for:human`                                  |

## Steps and performers

Every file in `steps/` defines one workflow step, and its `model:` frontmatter
selects who _performs_ it:

- **`model:` present** - an **ephemeral agent**. `tg` spawns a fresh `claude -p`
  (the file body is its system prompt), it does the step and exits. The example
  pipeline uses `opus` for the reviewer, `sonnet` for coder/open-pr/watch-pr.
- **no `model:`** - **you + the Driver**. The step surfaces in `tg mine`; the file
  body is a Driver skill for helping you do it (`review-plan`, `ready-merge`,
  `cleanup`). These are never spawned.

The Driver is the human's interactive seat and the performer of the human steps -
it composes its instructions from `driver.md` plus those step skills. It is defined
separately in `driver.md` (not under `steps/`, since it is not a single step);
`tg driver` launches it.

## Telemetry / logs

- `logs/workers.json` - role, bead (stamped at claim), pid, log path per worker.
  Each `tg sweep` (and so each run-loop tick) prunes dead entries, keeping all live
  workers plus the most recent `GRID_WORKER_HISTORY` dead ones (default 20) so
  `tg logs` can still reach recently finished workers.
- `logs/worker-<role>-<spawnid>.log` - each worker's output (`tg logs` finds it).
- `logs/run.log` - the run-loop's activity.
- Beads history gives cycle time, rework, throughput.

## Tests

```bash
bash tests/run.sh          # python3 -m unittest discover
```

## Tear down

`tg run` is foreground - Ctrl-C it. Workers are ephemeral and exit on their own.
If you backgrounded the loop yourself, find it with `tg ps` / kill the `tg run`
process.
