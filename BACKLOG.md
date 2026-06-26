# the-grid backlog

Future work, roughly in priority order. The engine is now beads-backed: a
persistent Driver + a non-AI supervisor that spawns ephemeral single-task agents
(coder/reviewer/pr-watcher), all work tracked as chained beads. See
`docs/superpowers/specs/` for the designs.

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
      Follow-ups: tg does not yet remove a worktree on story completion (finalize/cleanup
      step); and running the engine from a separate checkout than the target repo (a true
      separate TARGET_REPO) is still worth doing for dogfood safety.

## Still open (next design priorities)

- [ ] **Parallel agents up to MAX_AGENTS.** The model is N workers running ready jobs
      in parallel, not one-per-role serialised. The atomic claim already makes this
      safe (stress-tested: many concurrent claimers -> one winner each). Needs: the
      loop spawns up to MAX_AGENTS across all ready tasks (count live workers, not the
      per-role in-flight skip); logs keyed by task/spawnid not role (`tg logs <task>`,
      a way to multiplex/pick - `tg logs coder` assumes a single coder, which is wrong);
      and bd in SERVER mode (`bd daemon`/dolt sql-server) - embedded Dolt is
      single-writer, so concurrent worker writes need it. (See the bd server-mode item
      under Deferred - it is now a hard prerequisite, not optional.)
- [ ] **Handle subscription usage limits gracefully.** Today a worker that hits the
      Claude usage limit exits WITHOUT `tg done`; sweep reclaims the task and respawns
      it -> it hits the limit again -> respawn loop, no detection, no reason surfaced.
      All workers share ONE subscription quota, so one hit blocks everyone. Detect the
      signal in the worker's stream-json log (`You've hit your ... limit . resets
    <time>`; exit code is ~1 but undocumented - detect on the message, not the code),
      then PAUSE THE WHOLE LOOP (not just one task), surface "blocked: usage limit,
      resets <time>" to `tg mine`, and schedule a resume at reset. Resume is feasible -
      workers already get a unique `--session-id`, and `claude --resume <id> -p` replays
      context (only succeeds after reset). No built-in retry for quota limits.
- [ ] **Flow v2 (design: spec `GRID-002-flow-v2` in specs/).** Make "work off the tip
      of main" an invariant (fetch at branch, rebase-onto-tip at a new `open-pr` step,
      conflict -> block); split open-pr into `open-pr` (rebase + create PR) and
      `watch-pr` (CI/comments/remediate); and close the agent -> human -> agent loop by
      making `tg done` actor-agnostic with HUMAN-owned routable steps (`ready-merge`,
      `needs-human`, `cleanup`). Two return-edge kinds: rework -> build; block-resolution
      -> the recorded origin step. HARD CONSTRAINT: the whole workflow stays editable
      from agent markdown alone - `tg` provides primitives only, NO code-level builtins;
      the driver (CLU) fills human steps and supplies trigger signals by hand for now.
      Consolidates the "notes-forward on rework" and ad-hoc block/resume items.
- [ ] **Decouple the engine's data home for a deployed binary.** `steps/`, `.beads/`,
      and `logs/` still live at `grid_root` (where `bin/tg` resolves). Fine while
      dogfooding, but a deployed `tg` (not in the workspace) needs its data home set
      independently - a config key or `~/.local/share/the-grid` - distinct from the
      `projects`/`specs` roots (which are now HOME-configured).
- [ ] **Hide bd's id namespace from external ids.** Every bead id carries bd's
      per-store prefix (`the-grid-idz`, `the-grid-idz.1`); it is constant noise the
      `tg` surface should not expose - same "hide bd internals" line as bead->task.
      Doable: the prefix is discoverable (`bd config get issue_prefix` -> `the-grid`),
      so never hardcode it. Translate at the CLI boundary only - keep bd's canonical
      ids in the data layer, workers.json, and all bd calls; strip the prefix on
      every output (incl. the id/parent/deps fields inside `--json`), add it back on
      every id arg. Be lenient internalising (if an arg already has the prefix, use
      as-is - idempotent) and strict externalising. Keep the `.N` child suffix.
      Encapsulate the rule in one small value object/helper so there is a single
      place that knows the prefix; agents will round-trip the short ids, so the
      boundary must be airtight (a missed spot = "bead not found"). Needs thorough
      tests across every command that prints or accepts an id.
- [ ] **Visibility TUI.** `tg status`/`ps`/`logs` give the data; a live TUI that
      renders them (and tails a chosen worker) is the next ergonomic step. The
      `tg` layer was built precisely so the TUI is a thin renderer over it.
- [ ] **Notes-forward on rework (rejection detail).** Branch/PR now persist on the
      story, but the reviewer's rejection DETAIL (what to change) still only reaches
      the next coder via the bead title/notes, not as structured data. Watch whether
      the rework coder reliably gets it; consider `tg done --note` or a rejection
      artifact on the task.
- [ ] **pr-watcher / reviewer must read CI accurately.** Live, the pr-watcher
      misdiagnosed a CI failure (blamed Docker/network; it was a unit-test failure).
      Prompts now say "fetch the actual failing job/logs before concluding" - this
      is guidance, not enforced; verify it holds in a live run.

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

## Deferred (unchanged by tg)

- [ ] **External triggers (design first).** A coherent concept for anything that
      _automatically_ emits a signal or runs work OUTSIDE the agent markdown: merge
      auto-detection (poll `gh`/webhook), filesystem watchers, cron/schedules, git/PR
      hooks. Until designed, we resist codifying any such automation - the driver (CLU)
      supplies these signals by hand (and flow v2 keeps the workflow purely in agent
      files). The old "PR-merge auto-close loop" (detect merge -> cleanup -> close) is
      the first instance: it becomes an external trigger that emits `merged`, which the
      flow-v2 routing already handles. Think hooks vs cron vs watchers before building any.
- [ ] **bd embedded single-writer contention.** Embedded Dolt is single-writer; the
      run-loop spawns one role per tick (serialising enough for now). For real
      parallel workers, move beads to server mode (`bd daemon` / dolt sql-server).
- [ ] **Validate per-role model split with data.** opus driver+reviewer, sonnet
      coder+watcher. Use beads history (rework = build tasks per spec) to confirm the
      sonnet roles do not produce more rework.
- [ ] **Multiple branches/PRs per task.** Current model assumes one branch per task.

## Deferred subsystems (the bigger vision)

These were scoped out of the MVP deliberately. Each likely becomes its own spec.

- [ ] **WHAT/WHY refinement ("Quorra").** Interactive break-down of an
      untrustworthy PRD/ticket into provenance-tracked units the human can
      question, correct, and lock. This addresses the #1 pain (hallucination into
      durable artifacts) and feeds locked specs into the pipeline.
- [ ] **Provenance ledger / settled-facts store.** A durable record of claims with
      status (proposed -> under-review -> locked -> superseded) and source. The
      spec's Provenance table is the seed of this. (Reference: Open Knowledge
      Format.)
- [ ] **Inbox / capture ("remember this later").** First-class deferred items
      (todo/question/flag) that any actor - human or agent - can emit to a
      persistent queue, surfaced when relevant. Three entry paths: pull, refinement
      escalation, capture.
- [ ] **Planner.** Organises what needs the human's attention in priority order so
      the human is never the bottleneck.
- [ ] **Smart inbox triage.** An agent triggered when something lands in the human's
      real inbox (email/Slack) that triages "what do I need to do" across everything
      there, with helpful links and summaries. The Gmail/Slack/Calendar MCP tools make
      it concretely buildable. Sits at the intersection of Inbox/capture (the queue)
      and Planner (the prioritised surface), but event-driven off the actual inbox.
- [ ] **Measurement ("Recognizer").** Read `logs/supervisor.jsonl` + beads history +
      per-task transcripts to report rework count, cycle time, throughput, and where
      things go wrong - the same analysis used to design this system.

## Quality / known gaps

- [ ] **Reviewer vs Copilot gap.** The IL review skill historically misses things
      Copilot catches. Track `copilot_caught_missed` in done records and use it to
      strengthen the Reviewer prompt.
