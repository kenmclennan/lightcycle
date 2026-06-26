# Flow v2 - design

A redesign of the-grid's flow model, driven by what the first live runs taught us.
It makes "work off the tip of main" an invariant, splits the PR stage into focused
steps, and - the deep change - closes the **agent -> human -> agent** loop by making
the flow actor-agnostic.

Status: design. Implement on the hexagonal core (this design also informs where the
core boundaries fall).

## Why

The current flow is `build -> review -> open-pr -> ready-merge`, where `open-pr` (the
pr-watcher) does everything: rebase/branch hygiene, open the PR, read CI, handle
comments, decide done/rework. Live runs surfaced three gaps:

1. **Stale base.** A worker branches off `origin/main` at claim time; if main moves
   during its (often long) work, the branch goes stale. In one run the pr-watcher
   *correctly refused* to open a PR that would have reverted an unrelated change - but
   that protection was ad hoc, not a structural guarantee.
2. **open-pr does too much.** Rebase-and-create-PR is a one-shot; watch-CI-and-remediate
   is an ongoing loop. One agent doing both is two responsibilities.
3. **The loop is one-directional.** Agents emit outcomes and the flow routes them, but
   `for:human` is a dead end - resolving a block or merging a PR required hand-routing
   with raw `bd` calls. There is no defined human -> agent transition.

## The model

### Taxonomy of agent files (the one new idea that ties it together)

`tg` already assembles the flow from agent frontmatter. Generalise it by what each file
declares:

- **`model` + `step`** -> an **automated agent**. Owns the step, is spawnable, claims
  and works.
- **`step`, no `model`** -> a **human step**. Owns the step and has routes, but is never
  spawned; its tasks surface in `tg mine`, and the human advances them.
- **`model`, no `step`** -> the **driver** (the interactive seat; not a flow participant).

So a step's owner is just its file's name; whether it is *spawned* depends on `model`.
Routing works identically for human and agent steps. This is the whole mechanism for
closing the loop: the human is just another actor.

### Actor-agnostic `tg done`

`tg done <task> <outcome>` becomes the universal handoff - an **agent** calls it when it
finishes, and a **human** calls it for their own `for:human` tasks. The flow routes on
`(step, outcome)` regardless of who acted. `tg mine` shows each human task's available
outcomes (from its step's routes) so the human knows the options:

```
the-grid-wnv.4  ready-merge: GRID-001   outcomes: merged | changes
```

### The flow graph

```
build ----done----> review ----done----> open-pr ----done----> watch-pr ----done----> ready-merge ----merged----> cleanup -> (done)
  ^                   |  rejected            | conflict            | ci-failed             | changes
  |                   v                      v                     v                       v
  +<------------------+----------------------+---------------------+-----------------------+
  (rework / escalation edges all return to build, or to for:human)
```

- **`build`** (coder): unchanged, except the workspace is guaranteed fresh (below).
- **`review`** (reviewer): unchanged. `done -> open-pr`, `rejected -> build`.
- **`open-pr`** (NEW, one-shot agent): fetch, **rebase the branch onto the current tip of
  `origin/main`**, push, create the PR if absent (never a duplicate), link the `pr`
  artifact, `done -> watch-pr`. **Rebase conflict -> block(human)** (an agent can't safely
  auto-resolve a real conflict). This step is where the tip-of-main invariant lives.
- **`watch-pr`** (the renamed pr-watcher / remediator): poll CI + review comments;
  `done -> ready-merge` (green, comments resolved), `ci-failed -> build` (rework on the
  same branch/PR), `block(human)` when a human decision is needed.
- **`ready-merge`** (HUMAN step): the human merges on GitHub, then `tg done <task> merged`
  -> `cleanup`; or `tg done <task> changes` -> `build` (rework after review feedback).
- **`cleanup`** (agent or builtin): remove the worktree, close the story. Subsumes the
  deferred "PR-merge auto-close loop". (Later: auto-detect the merge by polling `gh` and
  emit `merged` automatically, instead of the human running `tg done ... merged`.)

### Tip-of-main invariant

Two enforcement points, so "are we on the tip?" stops being luck:

1. **At branch creation** (`ensure_worktree`): `git fetch origin` before
   `git worktree add ... origin/main`, so the coder starts from the true tip, not a stale
   local ref.
2. **At `open-pr`**: fetch + rebase onto `origin/main` before creating the PR. Clean ->
   proceed; conflict -> block(human) with resume-state. The PR is therefore always against
   fresh main.

### Closing the block -> resume loop

When an agent calls `tg block`, the task moves to a **`needs-human` step** (owned by the
human) carrying resume-state (the existing metadata) and a record of the **origin step**.
The human's outcomes on it:

- `resolved` -> route back to the origin step (the agent re-claims and reads the
  resume-state + the human's added note).
- `cancel` -> terminal.

This needs a small `tg` affordance for the human to attach their answer when resolving
(e.g. `tg done <task> resolved --note "..."`), so the resuming agent gets it as structured
data (also closes the deferred "notes-forward on rework" gap).

## What this asks of the core (informs the hexagonal refactor)

- **Flow engine**: routes are owner-agnostic; `owner[step] -> role` where role may be
  `human`; `spawnable(step)` iff the owning file has a `model`. `ready_roles` /
  spawn only consider spawnable owners.
- **`tg done`**: identical path for human and agent; validate `(step, outcome)` against the
  assembled routes; refuse unknown outcomes (already does).
- **`tg mine`**: list a human task's available outcomes (from `routes[step]`).
- **Worktree/Git port**: gains `fetch` + `rebase onto origin/main` + conflict detection as
  first-class operations (the open-pr step and ensure_worktree call them). Conflict is a
  domain outcome, not a crash.
- **Resume**: block carries origin-step + resume-state; `resolved` routes back. A human note
  rides along.

These are exactly the seams the hexagonal split should expose: a store port (bd), a git
port (fetch/rebase/worktree/push), a PR port (gh: create/poll/comments), a spawner port
(claude), with the pure flow/route/contract logic in the core.

## New / changed files

- `agents/open-pr.md` (new automated agent: rebase-onto-tip + create PR).
- `agents/watch-pr.md` (renamed from pr-watcher: CI + comments + remediate).
- `agents/ready-merge.md` (new HUMAN step: routes `merged -> cleanup`, `changes -> build`).
- `agents/needs-human.md` (new HUMAN step for blocks: `resolved -> <origin>`, `cancel -> -`).
- `agents/cleanup.md` (worktree removal + story close; may start as a builtin).
- `ensure_worktree`: fetch before branching.
- `tg block`: route to the `needs-human` step + record origin step.
- `tg done`: accept human-actor outcomes; `--note` for resume answers.
- `tg mine`: show available outcomes per task.

## Open questions

- **cleanup as an agent vs a builtin.** Worktree removal + story close is mechanical;
  it may be a `tg` builtin triggered by `merged` rather than a spawned agent.
- **Auto-merge detection.** Start manual (`tg done ... merged`); decide later whether the
  loop polls `gh pr view` to emit `merged` itself.
- **Rebase conflict UX.** On an open-pr rebase conflict, does the human resolve in the
  worktree and emit `resolved`, or do we hand it back to a coder with the conflict as
  context? Probably the former first.
- **Multiple human steps, one `tg mine`.** Ensure `tg mine` clearly distinguishes a
  ready-merge from a needs-human (a block) - different outcomes, different urgency.
