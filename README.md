# the-grid

A workflow-agnostic agent engine fronted by **`tg`**, a single Python CLI that owns
all work and its lifecycle. Work lives in **beads** (`bd`, hidden behind `tg`) as
tasks chained by dependencies. A run-loop spawns headless `claude -p` workers that
each claim one task, do it, and exit. tmux is optional - every part runs as a
standalone command. You define how you work by editing the agents in `agents/`; the
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
  has no opinion on *how you work* - including your spec format. It only stores a
  spec's path as an artifact; it never parses it. The agents in `agents/` are an
  *example* workflow (a feature pipeline: coder -> reviewer -> pr-watcher). You
  define your own way of working by editing and creating agents - their steps,
  routes, and whatever a "spec" means to them. A spec is whatever your agents
  understand; hand the Driver one you wrote and it flows in as-is.
- **Hierarchy: epic / story / task.** An **epic** is a goal; a **story** is a
  deliverable outcome (one spec -> one branch -> one PR) and **holds the
  artifacts**; a **task** is the work (a flow step under a story, or a standalone
  `tg add` item). `tg file` creates a story + its first task at the step you name.
- **Artifacts live on the story** as a `{type, value, label?}` list (spec, branch,
  pr, ticket, doc, ...). Tasks read their parent story's artifacts - nothing is
  copied between tasks.
- **Agents can declare an artifact contract** (optional) in frontmatter:
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
  stage. The chain is defined by the agents themselves: each agent declares its
  `step` and `routes:` (`outcome -> next-step`) in frontmatter, and `tg` assembles
  the flow from them - the next role is derived from whichever agent owns the next
  step (an unowned target is a `for:human` terminal). `tg flow` prints the
  assembled graph.
- **`tg` owns the domain and the processes.** It is the only caller of `bd`. It
  spawns/tracks workers and runs the loop. No tmux required.
- **Workers are ephemeral and claim their own task.** The loop spawns a role
  (`coder`/`reviewer`/`pr-watcher`); the worker's first act is `tg claim <role>`
  (atomic), then it works and exits. A worker that dies before claiming leaves
  nothing stuck.
- **`tg` owns worktree isolation.** On claim, `tg` creates (or reuses) a per-story
  git worktree on branch `grid/<story>` from `origin/main`, under a gitignored
  `.worktrees/<story>`, and hands the worker its path as the claim JSON's
  `workspace` field (it also auto-links the `branch` artifact). Workers do all git
  work there and never touch the primary tree - a worker can't switch the grid
  root's branch out from under the running loop.
- **Labels route work:** `for:<role>` (who acts next), `step:<step>` (flow step),
  `project:`/`goal:`. `for:human` tasks never auto-run; they surface to you.

## Commands

Initialise once with `tg init`, then run the parts in separate terminals.

| Command                                    | What it does                                                    |
| ------------------------------------------ | --------------------------------------------------------------- |
| `tg init`                                  | one-time: create the grid store for this project                |
| `tg run [--once]`                          | the loop: sweep, then start a worker for each role with work waiting |
| `tg driver`                                | open the interactive driver `claude` (your seat)                |
| `tg status`                                | all buckets: mine / active / queue / blocked                    |
| `tg mine`                                  | tasks that need you (`for:human`)                               |
| `tg active`                                | tasks being worked now                                          |
| `tg queue [N]`                             | next N upcoming agent tasks                                     |
| `tg ps [--json]`                           | running workers (role, bead, pid, alive)                        |
| `tg logs <task\|role\|run> [-f]`           | tail a worker's or the loop's log                               |
| `tg show <id>`                             | a story (artifacts + child tasks) or a task (+ story artifacts) |
| `tg trace <story>`                         | story + its artifacts + child tasks + logs                      |
| `tg flow [--json]`                         | print + check the assembled flow (steps, routes, contracts, composition) |
| `tg file <spec> --step <step> [--epic/--project/--goal]` | create a story (spec attached) + first task at `<step>` |
| `tg link <story> <type> <value> [--label]` | attach an artifact to a story                                   |
| `tg add "<title>"`                         | create a standalone human task (no story/flow)                  |
| `tg sweep`                                 | release orphaned claims (dead worker -> task reclaimable)       |
| `tg claim <role>`                          | (agents) atomically claim the next task for a role              |
| `tg done <id> <outcome>`                   | (agents) close with a flow outcome; advances the chain          |
| `tg block <id> --needs ...`                | (agents) escalate with resume-state -> `for:human`              |

## Models

Each role declares its own model in the `model:` frontmatter of its agent file
(`agents/<role>.md`): `opus` for driver+reviewer, `sonnet` for coder+pr-watcher.
`tg` reads it per spawn and refuses to spawn a role whose file lacks a `model:`.

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
