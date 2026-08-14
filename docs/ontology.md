# Ontology

The single source of truth for lightcycle's vocabulary. Every term used in the code, the specs, the step markdown, and in conversation should match a term here. Coining a synonym for an existing term is drift - fix the usage, or change this doc deliberately.

## The model (nouns)

- **node** - the atom. One row in the `nodes` table. Every theme, item, and step is a node; they differ by `type`, not by table.
- **theme** - a grouping of related work toward a goal. Optional: an item can stand alone.
- **item** - a unit of deliverable work. Carries artifacts. May have a parent theme.
- **step** - a single action performed by a role, filed from the workflow. A child of an item.
- **planned step** - a not-yet-filed future step, derived by walking an item's pinned workflow graph forward from its current step along the normal-completion edge. Display-only: never a real node, never claimed or advanced. Represented in code as `ProjectedStep`.
- **artifact** - a typed value attached to an item: `brief`, `spec`, `repo`, `branch`, `pr`, `design`, `findings`, `reflection`. `reflection` (an agent's feedback) accumulates; the others are single by convention (expressed in the step markdown, not the engine).
- **role** - who performs a step. For an agent step it is the step name itself (`write-code`, `review-code`, `audit`, ...); human steps carry the role `human`.
- **outcome** - how a step ended, and what drives the next transition: `done`, `approved`, `changes`, `rejected`, `drafted`, `merged`, `abandoned`, `conflicted`, `resolved`, `escalate`, `ci-failed`, `gave-up`, `findings`, `clean`, `reviewed`.
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
- **sweep** - reclaim orphaned or stalled step claims and prune dead worker records.
- **reclaim** - return a stalled or dead worker's step to `ready`.
- **stalled** - a claimed worker, past its boot window, whose log has not grown for longer than `stall-seconds` and has not yet issued a terminal command; killed on the next sweep.
- **probe cooldown** - after the breaker's own rate-limit probe is killed for stalling, `reset_at` is re-armed `probe-cooldown-seconds` forward rather than left at its stale value; a stall is inconclusive, never treated as a successful probe.
- **retro** - gather a theme's child feedback and signals into a digest.
- **read** - `show` (one node as JSON), `trace` (an item end-to-end: artifacts + child steps + logs), `status` / `inbox` / `backlog` / `active` / `queue` (lane views), `flow` (the assembled workflow), `worklog`.

## The workflow (how steps chain)

- **workflow** - the graph, defined in markdown: `entry`, `requires` (artifacts the item must carry to start), `workspace` (which repo a stage runs in), `nodes` (stage -> step file), `edges` (outcome -> next step), `hooks` (external event -> transition), `signals`.
- **step file** / **step markdown** - the prompt for a stage (`steps/<name>.md`, in a workflow source). Workflow policy and conventions live here; the engine stays agnostic.
- **entry** - the step filed when an item is activated.
- **edge** - `step  outcome  next-step`; a `next-step`-less edge declares the outcome terminal (closes, no new step).
- **hook** - an external event (a PR merge, close, or comment) mapped to a transition.
- **gate** - a human step that must close before downstream proceeds (e.g. the spec-phase `await-merge`, the spec-PR review gate).
- **signal** - a per-step counter or condition feeding cadence or escalation.
- **phase** - a group of stages sharing one PR and one worktree (spec, feature, code). It names _which_ gate, not when.
- **workspace** - which repo a stage's worktree is cut from. `project` (the default) is the item's own `repo` artifact; `specs` is the configured specs root; any other value names a registered project. An unregistered name is an error, never a silent fall back to the item's repo.
- **phase run** - one pass of an item through a phase. A workflow that loops re-enters a phase, and each run gets its own branch and worktree; the first run keys on the bare phase name, later runs carry their index (`spec-2`). Phase alone identifies a gate, never a pass.

## The spec-driven pipeline (steps)

Every step name is an **action**. The step name, its markdown file, and (for an agent step) the role you claim are the **same word** - one name, not two. The built-in `spec-driven` workflow is one arc: a brief becomes a formal spec on a spec PR, and once that PR merges the same item continues into the code build. `open-pr` and `await-merge` each appear twice (the spec phase and the code phase).

- **spec-writer** (agent) - author the formal spec from the item's brief, on a branch in the specs repo.
- **open-pr** (agent) - push the branch and open the PR (used at both the spec and code phases).
- **await-merge** (human) - you review and merge the PR; lightcycle never merges for you. The spec-phase `await-merge` is the review gate; merging it advances the SAME item into the code phase (no workflow flip).
- **write-code** (agent) - implement the merged spec on a branch in the project repo.
- **watch-ci** (agent) - wait for CI to go green.
- **review-code** (agent) - review the code on the PR.
- **handle-feedback** (agent) - interpret PR feedback (`@lc` mention or a review bot) and decide rework / answer / ignore.
- **cleanup** (human) - remove the worktree and branch; terminal.
- **resolve-conflict** (agent) - rebase and resolve merge conflicts.
- **review-conflict** (human) - the escalation endpoint when conflicts cannot be resolved.
- **review-ci** (human) - the escalation endpoint when CI keeps failing past the cap instead of looping write-code forever.

The periodic retro **audit** is no longer a workflow step - it is an **engine service** that runs across all workflows (any item that produces feedback is audited on a cadence), with findings surfaced in `lc inbox`. See the audit under the engine, not the workflow.

## Deployment (engine, data home, workflow sources)

- **engine** - the installed package (pipx venv): the code plus `prompts/` (the engine-owned agent prompts it spawns directly - `driver.md`, `audit.md`). Replaced wholesale by `lc upgrade`. The engine ships no workflow library; workflows are pulled.
- **data home** (`~/.lightcycle`, named by `LC_HOME`) - the store (`store.db`), config, logs, worktrees, and the pulled workflow bundles under `workflows/<origin>/<sha>/`. Never touched by `lc upgrade`.
- **workflow source** - a git repo (an **origin**) holding a `source.toml` manifest plus `workflows/*.md` and `steps/*.md`. The engine pulls it into an immutable, sha-pinned **bundle**; each item pins `<origin>/<name>@<sha>` at activation, and the loader resolves the flow and steps from that pin. Managed with `lc workflow add|upgrade|list|rm`. There is no `.lightcycle/` step/workflow override and no resolution chain - a pinned bundle is self-contained.

## Project registry

- **project** - a registered codebase lightcycle files work against: an **identity**, a **shortcode**, a local path, and a remote URL. Stored in the project registry, managed with `lc project add|list|rm`.
- **identity** - the canonical `owner/name` string parsed from a repo's GitHub remote (SSH or HTTPS); the registry's lookup key. A path with no parseable GitHub remote has no identity and cannot be registered.
- **shortcode** - the id prefix items registered under a project nest beneath (see "Identity" below). Explicit at registration (`--shortcode`) or defaulted from identity's name segment, uppercased. Per-project, not engine-wide.
- **scan** - `lc project scan [dir]`, read-only: walks a directory tree for git repos, classifying each as `new` (identity resolved, not yet registered), `already-registered`, or `no-remote` (no parseable GitHub remote). Registers nothing itself - a human or `lc project add` acts on its output.

## Identity

- **shortcode** - a project's id prefix (see "Project registry" above); every registered project has its own, not one engine-wide constant.
- **id nesting** - ids nest by parent: `LC-3` (theme), `LC-3.1` (item), `LC-3.1.1` (step) - `LC` here is one project's shortcode. A standalone item takes a top-level id.

## Naming discipline

- A term used anywhere must match this doc. A new concept gets added here first; a synonym for an existing one is drift.
- **Open rename candidate:** `trace` -> `inspect` (reads more naturally as "look closely at an item end-to-end"). Decide, then apply across the CLI, docs, and step markdown in one change.
