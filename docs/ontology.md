# Ontology

The single source of truth for lightcycle's vocabulary. Every term used in the code, the specs, the step markdown, and in conversation should match a term here. Coining a synonym for an existing term is drift - fix the usage, or change this doc deliberately.

## The model (nouns)

- **node** - the atom. One row in the `nodes` table. Every theme, item, and step is a node; they differ by `type`, not by table.
- **theme** - a grouping of related work toward a goal. Optional: an item can stand alone.
- **item** - a unit of deliverable work. Carries artifacts. May have a parent theme.
- **step** - a single action performed by a role, filed from the workflow. A child of an item.
- **artifact** - a typed value attached to an item: `spec`, `repo`, `branch`, `pr`, `design`, `feedback`. `feedback` accumulates; the others are single by convention (expressed in the step markdown, not the engine).
- **role** - who performs a step. For an agent step it is the step name itself (`write-code`, `review-code`, `audit`, ...); human steps carry the role `human`.
- **outcome** - how a step ended, and what drives the next transition: `done`, `approved`, `changes`, `rejected`, `drafted`, `merged`, `abandoned`, `conflicted`, `resolved`, `escalate`, `ci-failed`, `gave-up`.
- **state** - a node's single lifecycle position: `backlogged` -> `ready` -> `in_progress` -> `done`. One state machine (there is no separate `status`).
- **lane** - a derived view over `(state, role)`: `inbox` (human action + gates), `active` (running), `queue` (ready agent steps), `blocked`. Lanes are computed, never stored.

## The lifecycle (verbs)

- **activate** - move an item from `backlogged` into the flow by filing its entry step. Realized as `lc set <item> --state active`.
- **new** - create a node (`lc new theme|item|step`).
- **set** - update a node's fields (title, goal, desc, parent, state, ...).
- **attach** - add an artifact to an item (`lc attach`); `--replace` swaps a same-type artifact.
- **dep** - declare one node blocks another (`lc dep <id> --needs <id>`).
- **claim** - a worker atomically takes the next ready step for a role (`lc claim <role>`).
- **done** / **close** - close a node with an outcome (`lc done <id> <outcome>`); a step's outcome advances the flow.
- **advance** - file the next step for an outcome without closing (plumbing).
- **sweep** - reclaim orphaned step claims and prune dead worker records.
- **reclaim** - return a stalled or dead worker's step to `ready`.
- **retro** - gather a theme's child feedback and signals into a digest.
- **read** - `show` (one node as JSON), `trace` (an item end-to-end: artifacts + child steps + logs), `status` / `inbox` / `backlog` / `active` / `queue` (lane views), `flow` (the assembled workflow), `worklog`.

## The workflow (how steps chain)

- **workflow** - the graph, defined in markdown: `entry`, `nodes` (stage -> step file), `edges` (outcome -> next step), `hooks` (external event -> transition), `signals`.
- **step file** / **step markdown** - the prompt for a stage (`library/steps/<name>.md`). Workflow policy and conventions live here; the engine stays agnostic.
- **entry** - the step filed when an item is activated.
- **edge** - `step  outcome  next-step`.
- **hook** - an external event (a PR merge, close, or comment) mapped to a transition.
- **gate** - a human step that must close before downstream proceeds (e.g. `review-spec`, the spec-review gate).
- **signal** - a per-step counter or condition feeding cadence or escalation.

## The standard pipeline (steps)

Every step name is an **action**. The step name, its markdown file, and (for an agent step) the role you claim are the **same word** - one name, not two.

- **draft-spec** (human) - co-draft a spec from a seed.
- **review-spec** (human) - the entry gate; approve the spec or send it back.
- **write-code** (agent) - implement the spec on a branch.
- **open-pr** (agent) - push the branch and open the PR.
- **watch-ci** (agent) - wait for CI to go green.
- **review-code** (agent) - review the code on the PR.
- **handle-feedback** (agent) - interpret PR feedback (`@lc` mention or a review bot) and decide rework / answer / ignore.
- **await-merge** (human) - you merge the green PR; lightcycle never merges for you.
- **cleanup** (human) - remove the worktree and branch; terminal.
- **resolve-conflict** (agent) - rebase and resolve merge conflicts.
- **review-conflict** (human) - the escalation endpoint when conflicts cannot be resolved.
- **audit** (agent) - the cadence-spawned retro auditor.

## The three homes (deployment)

- **engine** - the installed package (pipx venv): the code plus the default workflow and steps shipped in `library/`. Replaced wholesale by `lc upgrade`.
- **data home** (`~/.lightcycle`) - the store (`store.db`), config, logs, worktrees. Never touched by upgrade. May override library steps and workflows.
- **project** - a target repo, optionally with a `.lightcycle/` override of steps, workflows, or config.
- **resolution order** for steps and workflows: project `.lightcycle/` -> data home -> engine `library/` (most specific wins).

## Identity

- **shortcode** - the id prefix (`LC`).
- **id nesting** - ids nest by parent: `LC-3` (theme), `LC-3.1` (item), `LC-3.1.1` (step). A standalone item takes a top-level id.

## Naming discipline

- A term used anywhere must match this doc. A new concept gets added here first; a synonym for an existing one is drift.
- **Open rename candidate:** `trace` -> `inspect` (reads more naturally as "look closely at an item end-to-end"). Decide, then apply across the CLI, docs, and step markdown in one change.
