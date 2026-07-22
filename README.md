# lightcycle

A workflow-agnostic agent engine fronted by **`lc`**, a single Python CLI that owns all work and its lifecycle. Work lives in a local SQLite store (hidden behind `lc`) as nodes chained by dependencies. A run-loop spawns headless `claude` workers that each claim one step, do it, and exit. tmux is optional - every part runs as a standalone command. You define how you work by composing **workflows** - routing graphs pulled from git **sources** - over reusable **steps**; the engine imposes no spec format or fixed pipeline, and different themes can run different workflows at once.

The name is the double meaning: work rides its **lifecycle** through the engine, and every node leaves a light-trail - the audit trail of what happened, when, and why.

The live backlog and roadmap live in the store - run `lc backlog` for open items, `lc status` for the whole picture.

## Prerequisites

- **`python3`** (3.11+, stdlib only - the engine has no pip deps)
- **`claude`** CLI, **signed in to a Claude subscription** (workers bill to your subscription, not the API). Run `claude` once and complete login before starting the pool.
- **`git`**, and **`gh`** (authenticated) for the PR steps and clone-on-demand at activation
- **`pipx`** to install the engine
- optional: **`glow`** (for `bin/lc-spec.sh` spec preview)

## Install

lightcycle is a pipx-installable package with an `lc` console entry point:

```bash
pipx install git+https://github.com/kenmclennan/lightcycle   # lc + lightcycle on PATH
lc init                                                       # create ~/.lightcycle (store + config)
```

Everything that is _yours_ lives in **`~/.lightcycle/`** (config, store, logs, worktrees, and the workflow bundles pulled from origins) - separate from the installed engine, so a `pipx` upgrade never touches your data. `~/.lightcycle` is found by default (override with `$LC_HOME`).

## Quickstart

```bash
# 0. one-time prereq: sign in to your Claude subscription
claude            # complete login, then exit

# 1. install + initialise
pipx install git+https://github.com/kenmclennan/lightcycle
lc init                              # creates ~/.lightcycle (store + config); pulls the built-in workflow origin
lc config --edit                     # point `projects` + `specs` at your dirs (defaults: ~/workspace/{projects,specs})

# 2. tell lightcycle about a repo you want it to work in
#    (any git repo under your `projects` dir)
lc project add owner/myapp --path ./myapp   # register a project in the registry

# 3. drive some work in
lc new theme "Add a health endpoint" --workflow lightcycle/spec-driven   # open the focus area; prints a theme id, e.g. MYAPP-1
item=$(lc new item "health endpoint" --parent MYAPP-1)   # a todo item under the theme
lc attach $item brief specs/health-brief.md    # the co-designed brief
lc attach $item repo myapp                     # the target repo
lc set $item --state active                    # files spec-writer; it authors the spec on a spec PR

# 4. run the pool (separate terminal) and watch
lc start                             # the agent loop: claims ready steps, spawns workers, advances the flow
lc status                            # inbox / active / queue / blocked, all at once
lc driver                            # your interactive seat to shape specs and clear gates
```

`lc start` runs in the foreground and shows the neon banner as it comes online; Ctrl-C stops it (workers are ephemeral and exit on their own). The pool runs the agent steps; you drive from `lc driver` and clear the human gates (the spec PR, `await-merge`) that surface in `lc inbox`.

**Developing the engine itself?** Work in a checkout and run it directly (`python -m lightcycle.cli …`, or the `bin/lc` shim) so you dogfood your changes; use `bin/setup` for the dev environment (`uv` + tests). See [DEVELOPING.md](DEVELOPING.md).

## Model

Everything is a **node** - `theme`, `item`, or `step` - and the CLI is a small set of generic primitives over nodes (`new`/`set`/`show`/`done`/`rm`/`attach`/`dep`, plus `claim`). The workflow supplies the meaning; the engine ships no per-workflow verbs.

- **The engine is workflow-agnostic.** `lc` owns nodes and the flow, but has no opinion on _how you work_ - including your spec format. It only stores a spec's path as an artifact; it never parses it. The built-in `spec-driven` workflow is an _example_ (brief -> spec PR -> write-code -> open-pr -> watch-ci -> review-code -> await-merge -> cleanup). You define your own way of working by composing [workflows](#workflows), authored in a pullable **source**. A spec is whatever your steps understand.
- **Hierarchy: theme / item / step.** A **theme** is a focus area grouping related work (durable, often long-lived, and optional); an **item** is the unit you plan and ship (one spec -> one branch -> one PR) and **holds the artifacts**; a **step** is one stage of the item's workflow running (or the reusable step definition). An item is **stateful**: `todo` (captured) -> `active` (planned, running steps) -> `closed`. `lc new item` captures a todo; `lc set <item> --state active` **plans** it - filing the workflow's entry step, and first ensuring the item's repo is cloned if the registry knows it but it isn't checked out here yet.
- **Artifacts live on the item** as a `{type, value, label?}` list (brief, spec, branch, pr, repo, ...) via `lc attach`. Steps read their parent item's artifacts - nothing is copied between steps.
- **Steps can declare an artifact contract** (optional) in frontmatter: `accepts:` (inputs) and `produces:` (outputs), keyed by artifact type (`<type>: required|optional`). A required input gates the work; an optional input is read if present but never gates (e.g. write-code accepts `branch: optional`, since on a rework pass the branch already exists). `lc` enforces the required parts mechanically: a step whose required inputs are absent routes to `for:human` instead of running (precondition); `lc done` refuses to close until the required outputs are attached (postcondition); activating an item (`lc set --state active`) rejects an entry step whose inputs the item's artifacts can't satisfy; and `lc workflow check` statically checks the whole pipeline composes - every step's required inputs are guaranteed by some upstream producer on every path. Presence-only: it checks the item's artifact list, never git/GitHub reality. Agents with no contract are unconstrained.
- **A step is a stage running.** "write-code", "open-pr", "review-code" are steps chained by dependencies; closing one makes its dependents ready. Which step is ready IS the stage. The chain is defined by the **workflow graph** (see [Workflows](#workflows)), not by the steps: a workflow file names the entry stage, the `outcome -> next-stage` edges, and which step file performs each stage. `lc` resolves each step's workflow (from its item) and routes its outcome through that graph - the next performer is the step file the target stage maps to (an unowned target is a `for:human` terminal). `lc workflow check` prints the graph.
- **`lc` owns the domain and the processes.** It is the only caller of the store. It spawns/tracks workers and runs the loop. No tmux required.
- **Workers are ephemeral and claim their own step.** The loop spawns a role (`write-code`/`open-pr`/`watch-ci`/`review-code`); the worker's first act is `lc claim <role>` (atomic), then it works and exits. A worker that dies before claiming leaves nothing stuck. Human steps (`await-merge`/`cleanup`) are never spawned; they surface in `lc inbox`.
- **Three homes: engine / `~/.lightcycle` / projects.** The **engine** is the pipx-installed package - code plus `prompts/` (the engine-owned agent prompts it spawns directly: `driver.md`, `audit.md`). It ships no workflow library. **`~/.lightcycle/`** is everything that is _yours_: `config`, the store (`store.db`), `logs/`, `.worktrees/`, and the **pulled workflow bundles** under `workflows/<origin>/<sha>/` - independent of the engine, so upgrades never touch it (found by default, or `$LC_HOME`). **`projects/`** is the conventional default location for your repo checkouts - it's just where `lc project add --path` and `lc workflow init` conventionally point; the engine does not require repos to live there (see the project registry below).
- **Workflows come from pullable sources, not the engine.** A **workflow source** is a git **origin** holding `source.toml` + `workflows/*.md` + `steps/*.md`; the engine pulls it into an immutable, sha-pinned **bundle**, and each item pins `<origin>/<name>@<sha>` at activation. The loader reads the flow and steps from that pin - there is no `.lightcycle/` override and no resolution chain. `lc init` pulls the built-in `lightcycle` origin (`workflows-remote`); `lc workflow add|upgrade|list|rm` manages origins; author your own with the plugin's `author-workflow` skill.
- **The config names where your work lives.** `~/.lightcycle/config` (or `$LC_CONFIG`) names `projects` (the dir whose named subdirs are repos; default `~/workspace/projects`) and `specs` (base for relative spec paths; default `~/workspace/specs`), plus the global `shortcode` (id prefix), `default-origin`, and `workflows-remote`. There is **no default workflow**: activation requires an explicit or theme-inherited `--workflow <origin>/<name>`. `lc init` seeds it; `lc config [--edit]` shows or edits it.
- **The project registry: a project is its GitHub identity.** A project is registered by its `owner/name` GitHub identity in the store's `projects` table, via `lc project add <owner/name> [--shortcode X] [--path P]`; `lc project list` shows every registered project and its checkout status, `lc project rm <owner/name>` unregisters one (the checkout on disk is left alone). A registered project can have its own `shortcode` (new theme ids under it mint as `SHORTCODE-N`, and it's the prefix its specs use); a project absent from the registry, or matched ambiguously, inherits the global `shortcode`. `lc project scan [dir]` walks `dir` (default the current directory) for git repos and lists each as a candidate - its derived `owner/name`, a proposed shortcode, and whether it's new, already registered, or has no usable GitHub remote; `--json` emits the same list as structured data (`identity`, `path`, `shortcode`, `status`, `remote`, `registered_path`, `registered_shortcode` - `null` where not applicable). It never registers anything itself.
- **One repo per item, anywhere.** An item targets exactly one repo, named by a `repo` artifact (`lc attach <item> repo <owner/name-or-path>`). The engine resolves that artifact through the project registry to the registered `local_path`; a bare name resolves when it unambiguously matches one registered identity's trailing segment, and an absolute path is used as-is with no registry lookup - repos need not live under `projects/`. A registered project with no local checkout is cloned into `<projects>/<owner>/<name>` via `gh repo clone` when the item is activated (`lc set --state active`); only an unregistered or ambiguous name is still a clear error, and a clone/auth failure fails activation without filing a step. Cross-repo work is handled by splitting the spec into one item per repo, never by a multi-repo workspace.
- **`lc` owns worktree isolation.** On claim, `lc` creates (or reuses) a per-item git worktree of the item's repo on branch `feat/<slug>` (the `branch-prefix` config, default `feat`) from `origin/main`, under `~/.lightcycle/.worktrees/<item>`, and hands the worker its path as the claim JSON's `workspace` field (it also auto-attaches the `branch` artifact). The spec lives under `specs`, so the claim JSON also carries `spec_path` (absolute) - workers read the spec from there and do all git work in the worktree, never touching the primary tree.
- **Labels route work:** `for:<role>` (who acts next), `step:<step>` (flow stage), `project:`/`goal:`. `for:human` steps never auto-run; they surface to you.

## Workflows

A **workflow** is a routing graph over a set of steps, authored as markdown in a **source** - a git **origin** with a `source.toml` manifest, `workflows/*.md`, and `steps/*.md`. **Steps are reusable prompts** (`steps/*.md`, carrying `model` + the optional `accepts`/`produces` contract); the **workflow owns the routing**. A source is self-contained and immutable once pulled: the engine pins each item to a `<origin>/<name>@<sha>` bundle under `~/.lightcycle/workflows/`.

The built-in `lightcycle` origin ships one workflow, **`spec-driven`**: a brief becomes a formal spec on a spec PR, and once that PR merges the same item continues into the code build (`write-code -> open-pr -> watch-ci -> review-code -> await-merge`). The spec PR is the human review gate; `open-pr`/`await-merge` appear at both the spec and code phases, each with its own `workspace` (the specs repo, then the project repo).

A workflow file has these sections; only `entry` is required:

```
# spec-driven

entry: spec-writer
requires: brief repo        # artifacts the item must carry to start

workspace:                  # which repo a stage runs in (default: project)
  spec-writer  specs

nodes:                      # stage -> step file (when one step serves two positions)
  spec-open-pr  open-pr

edges:                      # from-stage  outcome  to-stage
  spec-writer       done         spec-open-pr
  spec-await-merge  spec-merged  write-code
  write-code        done         code-open-pr

hooks:                      # engine event -> handling stage (+ value)
  pr_merge  code-await-merge  merged

signals:                    # stage  metric-name  outcome
  review-code  review_rounds  rejected
```

- Each **stage** names a step file (step = file = role by default). The `nodes:` block maps a stage to a differently named file (or one step serving two positions); a target with no step file is a `for:human` terminal, and a step with no `model` is a human step.
- The engine recognises a fixed set of **hooks** (`pr_merge`, `pr_close`, `pr_feedback`, `pr_conflict`/`_cap`/`_escalate`, `ci_failed_cap`, `mention_token`, `review_bot_allowlist`); the graph names which stage handles each. A workflow that omits `pr_*` never opens a PR.
- The periodic retro **audit** is an **engine service**, not a workflow step - any item that produces feedback is audited on a cadence, with findings in `lc inbox`.
- `lc workflow add <url>` validates a source at pull time; `lc workflow check [--json]` prints and statically checks the resolved graph.

**Selecting a workflow.** There is no default; selection lives on the theme and its items inherit it:

```bash
lc new theme "ship the thing" --workflow lightcycle/spec-driven
lc set <item> --state active                                     # inherits the theme's workflow
lc set <item> --state active --workflow lightcycle/spec-driven   # or name it per item
```

Because selection is per node, two themes can run different workflows concurrently. To customise or add a workflow, author a **source** (the plugin's `author-workflow` skill guides it) and `lc workflow add` it - you never edit files inside the engine.

## Commands

The mutating CLI is a small set of generic primitives over nodes; the read views and engine ops sit alongside. Initialise once with `lc init`, then run the parts in separate terminals.

**Node primitives**

| Command | What it does |
| --- | --- |
| `lc new <type> "<title>" [--parent/--workflow/--goal/--project]` | create a node; `<type>` is `theme`\|`item`\|`step` (validated) |
| `lc set <id> [--parent/--state/--workflow/--title/--goal/--label]` | update a node; `--parent` **moves** it; `--state active` plans an item (files its entry step); `--state ready`/`blocked` unblocks/escalates a step |
| `lc show <id>` | one node as JSON (artifacts, resume-state) |
| `lc done <id> [<outcome>]` | close a node; a **step** done-with-outcome advances the flow; an item/theme cascades |
| `lc rm <id>` | delete a node |
| `lc attach <id> <type> <value> [--label]` | attach an artifact (brief/spec/branch/pr/repo/...) |
| `lc dep <id> --needs <id>` | link one node as a blocker of another |
| `lc claim <role>` | (agents) atomically claim the next ready step for a role |

**See what's happening / run**

| Command | What it does |
| --- | --- |
| `lc init` | create `~/.lightcycle` (store + config); run once |
| `lc project <add\|list\|rm\|scan>` | manage the project registry: `add <owner/name> [--shortcode X] [--path P]`, `list`, `rm <owner/name>`, `scan [dir] [--json]` discovers git repos under `dir` (default cwd) as registration candidates - read-only |
| `lc config [--edit]` | show (or `--edit`) the lightcycle config: projects + specs roots |
| `lc start [--once]` | the agent pool: sweep, then fill up to `LC_MAX_AGENTS` workers from the ready queue |
| `lc driver` | open the interactive driver `claude` (your seat) |
| `lc status` | all buckets: inbox / active / queue / blocked |
| `lc inbox [N]` / `lc backlog [N]` | what needs you now (gates + blocked) / todo items to develop later |
| `lc active` / `lc queue [N]` / `lc ps` | steps running now / next N agent steps / running workers |
| `lc logs <step\|role\|run> [-f]` | tail a worker's or the loop's log |
| `lc trace <item> [--json]` | an item end to end: artifacts + child steps + logs |
| `lc workflow check [--json]` | print + check the assembled flow (stages, routes, contracts, composition) |
| `lc sweep` | release orphaned claims (dead worker -> step reclaimable) |

## Steps and performers

Every file in `steps/` is a reusable step prompt (routing lives in the [workflow](#workflows), not here). Its `model:` frontmatter selects who _performs_ it:

- **`model:` present** - an **ephemeral agent**. `lc` spawns a fresh `claude` (the file body is its system prompt), it does the step and exits. The example pipeline uses `opus` for review-code, `sonnet` for write-code/open-pr/watch-ci.
- **no `model:`** - **you + the Driver**. The step surfaces in `lc inbox`; the file body is a Driver skill for helping you do it (`await-merge`, `cleanup`, `review-conflict`). These are never spawned.

The Driver is the human's interactive seat and the performer of the human steps - it composes its instructions from `driver.md` plus those step skills. It is defined separately in `driver.md` (not under `steps/`, since it is not a single step); `lc driver` launches it.

## Telemetry / logs

- `logs/workers.json` - role, step (stamped at claim), pid, log path per worker. Each `lc sweep` (and so each run-loop tick) prunes dead entries, keeping all live workers plus the most recent `LC_WORKER_HISTORY` dead ones (default 20) so `lc logs` can still reach recently finished workers.
- `logs/worker-<role>-<spawnid>.log` - each worker's output (`lc logs` finds it).
- `logs/run.log` - the run-loop's activity.
- Node history gives cycle time, rework, throughput.

## Tests

```bash
bash tests/run.sh          # the full suite via uv + pytest (dev tooling only)
```

## Tear down

`lc start` is foreground - Ctrl-C it. Workers are ephemeral and exit on their own. If you backgrounded the loop yourself, find it with `lc ps` / kill the `lc start` process.
