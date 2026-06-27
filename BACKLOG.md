# the-grid backlog

The live backlog now lives in **bd** - run `tg backlog` for the open items and
`tg inbox` for what needs you (capture new ideas with `tg add`). Specs live in the
`specs` root (`GRID-NNN-*.md`). This file is now the **resolved-history archive**:
a record of what each major reframe settled, kept for context.

## Resolved by the beads + supervisor engine

- [x] **Context cleanup between tasks.** Dissolved: ephemeral workers carry one
      task's context and exit, so there is nothing to `/clear`. (The Driver is the
      only long-lived agent; do not `/clear` it.)
- [x] **"What next / where are we" gap.** Resolved by `tg`: `tg status` / `tg mine`
      / `tg queue` / `tg active` / `tg ps` project beads state from the driver's
      seat (or any terminal).

## Resolved by the `tg` domain layer

- [x] **Hide the bead abstraction.** `tg` is the single front door; agents and the
      human use `tg` verbs, never raw `bd`. Prompts speak "task", not "bead".
- [x] **Kill-and-resume idempotency.** `tg sweep` releases orphaned claims (resets
      status open AND clears assignee) for any in_progress task whose worker PID is
      dead; runs each `tg run` tick.
- [x] **Escalation + handoff contract.** `tg block <id> --branch --pr --reason
--tried --needs` writes structured resume-state to bead metadata and routes to
      `for:human`; available to every role. `tg done` validates the outcome against
      the flow and refuses unknown outcomes rather than dropping work.
- [x] **Ephemeral workers actually exit.** Workers run `claude -p` (headless),
      spawned via Popen and tracked in `logs/workers.json`; they exit on completion.
      tmux is no longer load-bearing.

## Orchestration bugs - must fix before unattended runs (first live run, 2026-06-25)

The first dogfood run (story the-grid-idz, a one-line banner fix) produced the
correct code change but surfaced three orchestration bugs. The run was paused and
the fix landed manually (commit d3b46b5).

- [x] **Double-claim (FIXED).** Root cause was NOT bd: `bd --claim` is atomic across
      processes (verified). The bug was a TOCTOU in tg's two-step claim - `bd --claim`
      flips the task to in_progress, but ownership was recorded separately in
      `workers.json` (`stamp_bead`) a few hundred ms later; `sweep` judged "orphaned"
      from that lagging registry field, reset the just-claimed task to open, and a
      second worker re-claimed it. Fixed by making the bd assignee the single source
      of truth: a worker claims under its unique spawnid (via GIT_CONFIG env override,
      atomic with the claim), and sweep keys liveness off assignee -> spawnid -> pid
      (a mapping written at spawn, so it never lags). Verified with a 6-claimer +
      concurrent-sweeper stress test: exactly one winner.
- [x] **Over-spawn: poll interval << worker boot time (FIXED).** The loop spawned a
      worker per ready role every 5s tick, but `claude -p` takes ~10-30s to boot and
      claim, so the same ready task triggered a fresh spawn every tick (~7 coders for
      one task). Fixed: `_run_tick` skips a role that has an "in flight" worker - one
      that is alive but has not yet claimed (registry `bead` is None). Now exactly one
      worker boots per role until it claims (or dies), then the next can spawn.
      A worker stuck booting past GRID_MAX_BOOT_SECONDS (default 120) no longer
      blocks its role - the atomic claim keeps a late extra spawn safe.
- [x] **Workers branch in-place instead of in an isolated worktree (FIXED).** The coder
      ran `git checkout -b` in its cwd (the repo root) rather than `git worktree add`,
      switching the main working tree to the feature branch with uncommitted edits. The
      prompt said "worktree" but it was unenforced guidance. Fixed: `tg` now owns
      worktree creation. `tg claim` calls `ensure_worktree(story)` - fresh story ->
      `git worktree add .worktrees/STORY -b grid/STORY origin/main`; rework (worktree or
      branch already exists) -> reuse it (idempotent) - and returns the path as a
      `workspace` field in the claim JSON. It also auto-links the `branch` artifact, so
      the coder no longer links it by hand. `.worktrees/` is gitignored. The agent
      prompts now `cd` into `.workspace` and forbid any `git checkout`/`branch`/`worktree`
      in the grid root, so a worker can never mutate the primary tree. Falls back (no
      `workspace`, no mutation) when there is no `origin/main`.

## Resolved by the stories & artifacts reframe

- [x] **Epic/story/task hierarchy.** epic=goal, story=deliverable, task=work.
      `tg file` creates a story + first build task; `advance` parents every task to
      the story (`--parent`), fixing the orphaned-flow-bead bug (flow beads no longer
      fall out of the hierarchy).
- [x] **Uniform artifacts on the story.** `{type,value,label}` list in story
      metadata; `tg link` attaches any artifact; `tg show`/`tg trace` surface them.
      Replaced the special-cased spec-note + branch/pr-metadata. Tasks read their
      parent story's artifacts (no carry-forward). `tg set` removed.
- [x] **Trace view.** `tg trace <story>` ties spec, branch, PR, child tasks, and
      logs together in one place.
- [x] **`tg-` id prefix.** Tool-neutral handles; project/goal identity lives in the
      epic + labels, not the id.

## Resolved by the rework-identity fix (live snag, now superseded by the story model)

- [x] **Rework branch + PR identity.** Branch + PR are now attached once to the
      STORY; every rework task under it sees them - no carry-forward, no drift, no
      superseding PRs. (Earlier fix used per-task carry-forward + `tg set`; the story
      model makes it structural.)
- [x] **`open-pr -> build` rework path.** Added `open-pr ci-failed build coder`;
      pr-watcher emits `tg done <id> ci-failed` to rework on the same branch/PR.
