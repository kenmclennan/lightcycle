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
- [ ] **Over-spawn: poll interval << worker boot time.** The loop spawns one worker
      per ready role per tick (5s), but `claude -p` takes ~10-30s to boot and claim,
      so the same ready task triggers a fresh spawn every tick until one claims
      (~7 coders for one task). Fix: don't spawn a role that already has a live
      worker which hasn't claimed/exited (track unclaimed live workers), and/or add
      a per-role spawn cooldown.
- [ ] **Workers branch in-place instead of in an isolated worktree.** The coder ran
      `git checkout -b` in its cwd (the repo root) rather than `git worktree add`,
      switching the main working tree to the feature branch with uncommitted edits.
      The coder prompt says "worktree" but it is guidance, not enforced. Have `tg`
      create the worktree and hand the worker its path (spawn cwd = worktree), so a
      worker can never mutate the primary tree. Especially hazardous when dogfooding:
      target repo == engine repo == the running loop's source, so a worker edits the
      live engine. Consider running the engine from a separate checkout than the
      target repo.

## Still open (next design priorities)

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

- [ ] **PR-merge auto-close loop.** Detect a merge (poll/webhook), run cleanup
      (worktree + branch removal), close the task. The pr-watcher stops at "ready for
      human merge"; a human merges.
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
- [ ] **Measurement ("Recognizer").** Read `logs/supervisor.jsonl` + beads history +
      per-task transcripts to report rework count, cycle time, throughput, and where
      things go wrong - the same analysis used to design this system.

## Quality / known gaps

- [ ] **Reviewer vs Copilot gap.** The IL review skill historically misses things
      Copilot catches. Track `copilot_caught_missed` in done records and use it to
      strengthen the Reviewer prompt.
