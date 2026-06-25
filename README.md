# the-grid

An agent pipeline fronted by **`tg`**, a single Python CLI that owns all work and
its lifecycle. Work lives in **beads** (`bd`, hidden behind `tg`) as tasks chained
by dependencies. A run-loop spawns headless `claude -p` workers that each claim one
task, do it, and exit. tmux is optional - every part runs as a standalone command.

See `BACKLOG.md` for the roadmap and known gaps, and `specs/SPEC-TEMPLATE.md` for
the spec format that feeds the pipeline.

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

- **Hierarchy: epic / story / task.** An **epic** is a goal; a **story** is a
  deliverable outcome (one spec -> one branch -> one PR) and **holds the
  artifacts**; a **task** is the work (a flow step under a story, or a standalone
  `tg add` item). `tg file` creates a story + its first build task.
- **Artifacts live on the story** as a `{type, value, label?}` list (spec, branch,
  pr, ticket, doc, ...). Tasks read their parent story's artifacts - nothing is
  copied between tasks.
- **Everything is a task.** "build", "review", "open-pr" are tasks chained by
  dependencies; closing one makes its dependents ready. Which task is ready IS the
  stage. The chain lives in `flows/feature.tsv` - `tg` is flow-agnostic.
- **`tg` owns the domain and the processes.** It is the only caller of `bd`. It
  spawns/tracks workers and runs the loop. No tmux required.
- **Workers are ephemeral and claim their own task.** The loop spawns a role
  (`coder`/`reviewer`/`pr-watcher`); the worker's first act is `tg claim <role>`
  (atomic), then it works and exits. A worker that dies before claiming leaves
  nothing stuck.
- **Labels route work:** `for:<role>` (who acts next), `step:<step>` (flow step),
  `project:`/`goal:`. `for:human` tasks never auto-run; they surface to you.

## Commands

Run the parts standalone, or use `tg up` to start them together.

| Command                                    | What it does                                                    |
| ------------------------------------------ | --------------------------------------------------------------- |
| `tg up`                                    | ensure beads, background `tg run`, open the driver              |
| `tg run [--once]`                          | the loop: sweep, then spawn a worker per ready role             |
| `tg driver`                                | open the interactive driver `claude` (your seat)                |
| `tg status`                                | all buckets: mine / active / queue / blocked                    |
| `tg mine`                                  | tasks that need you (`for:human`)                               |
| `tg active`                                | tasks being worked now                                          |
| `tg queue [N]`                             | next N upcoming agent tasks                                     |
| `tg ps [--json]`                           | running workers (role, bead, pid, alive)                        |
| `tg logs <bead\|role\|run> [-f]`           | tail a worker's or the loop's log                               |
| `tg show <id>`                             | a story (artifacts + child tasks) or a task (+ story artifacts) |
| `tg trace <story>`                         | story + its artifacts + child tasks + logs                      |
| `tg file <spec> [--epic/--project/--goal]` | create a story (spec attached) + first build task               |
| `tg link <story> <type> <value> [--label]` | attach an artifact to a story                                   |
| `tg add "<title>"`                         | create a standalone human task (no story/flow)                  |
| `tg sweep`                                 | release orphaned claims (dead worker -> task reclaimable)       |
| `tg claim <role>`                          | (agents) atomically claim the next task for a role              |
| `tg done <id> <outcome>`                   | (agents) close with a flow outcome; advances the chain          |
| `tg block <id> --needs ...`                | (agents) escalate with resume-state -> `for:human`              |

## Models

Each role runs on its own model from `config/models.json` (`opus` driver+reviewer,
`sonnet` coder+watcher by default). `tg` reads it per spawn.

## Telemetry / logs

- `logs/workers.json` - role, bead (stamped at claim), pid, log path per worker.
- `logs/worker-<role>-<spawnid>.log` - each worker's output (`tg logs` finds it).
- `logs/run.log` - the run-loop's activity.
- Beads history gives cycle time, rework, throughput.

## Tests

```bash
bash tests/run.sh          # python3 -m unittest discover
```

## Tear down

`tg run` is foreground - Ctrl-C it. Workers are ephemeral and exit on their own.
If `tg up` backgrounded the loop, find it with `tg ps` / kill the `tg run` process.
