# Measuring TUI performance

`lc tui` polls `LightcycleApp._refresh()` every `POLL_INTERVAL_SECONDS` (10s, `app.py:69`). This document is the method for finding out where a tick's time and memory go, and this item's own measurement run against it.

## Two tools, two questions

**`py-spy`** (sampling, attaches to a running `lc tui` process by PID, ~1% overhead, no code changes) answers "where does wall-clock time go" - it finds slow code.

```
pgrep -f "lightcycle.*tui"
py-spy record -o tui.svg --pid <pid> --duration <seconds>
```

Add `--idle` to include idle/await time in the flame graph. Textual is asyncio - `_refresh()` spends most of its life awaiting the event loop between ticks, so an idle-excluded chart under-represents wall time and an idle-included chart can be misread as "working" when it is actually "awaiting". State in any write-up which was used.

**`cProfile`** (deterministic, stdlib, distorting) answers "how many times was this called" - it finds repeated code, the [[LC-520]] bug class this item is chasing the residue of.

```
python -m cProfile -o /tmp/tui.prof -m lightcycle tui
python -m pstats /tmp/tui.prof
```

Inside `pstats`, `sort ncalls` then `stats N` - never `sort cumulative` for this question, since cProfile's own overhead distorts absolute timings and only call counts are trustworthy.

Capture **many ticks, not one**. A 30-second `py-spy` capture gives three ticks at the real 10s interval; prefer minutes, to see a steady state rather than one sample.

## The counter

A lightweight, config-gated counter records each `_refresh()`'s wall duration and the process's own RSS, appended to the existing run log - no profiler, no code path change, near-zero cost when off.

Turn it on with `tui-metrics: true` in `~/.lightcycle/config`, or `LC_TUI_METRICS=true`. Samples land in `<data_root>/logs/run.log` - `~/.lightcycle/logs/run.log` by default (`config.py`'s `data_root()`/`default_data_root()`). Each line:

```
10:20:29  tui      wall_ms=79 rss_kb=82384
```

`wall_ms` is `_refresh()`'s own wall-clock duration in milliseconds; `rss_kb` is the process's RSS in kilobytes at the end of that tick, or `?` when it could not be read.

## Contention and the memory gate

Before recording a figure taken with the pool at `max-agents`, check `lc config`'s current `memory-reserve-fraction`/`suspend-pressure`/`resume-pressure` values and state here whether [[LC-506]]'s admission/suspension gate was active or neutered on the machine the measurement was taken on - the brief recorded it neutered (`memory-reserve-fraction: 0`, `suspend-pressure: 0.99`) as of 2026-09-15; this can change, so record what was actually true at measurement time, not what a past write-up said.

## Results (this item's measurement run, 2026-09-15)

**Setup.** The store snapshot used for this run is a point-in-time copy of this machine's own live `~/.lightcycle/store.db` (113 real nodes, taken via `sqlite3 .backup` so the live database was never opened for writing) plus a copy of `~/.lightcycle/workflows`, loaded from an isolated `LC_HOME` - the live store itself was never pointed at directly. This gives production-shaped data (real item/step counts and structure) without the risk of a live-store test run. `_refresh()` was driven directly (`LightcycleApp._refresh()` under Textual's `run_test()` harness, the same call `session.run(session.app._refresh)` makes in the test suite) rather than through a real interactive terminal session, because the profiling and counter code paths are identical either way and this removes the need for a pty. `tui-metrics: true` was set for the whole run, so every figure below came from the shipped counter, not a one-off instrument.

**The memory gate, checked at measurement time.** `~/.lightcycle/config` on this machine currently reads `memory-reserve-fraction: 0`, `suspend-pressure: 0.99`, `resume-pressure: 0.70` - confirmed neutered, matching the brief's 2026-09-15 record. No real agent pool was started for this run (spinning real `claude`-backed workers to generate genuine CPU/memory contention is a cost and blast-radius call beyond what this measurement pass makes on its own); the figures below characterise a single `lc tui` process's steady-state tick, not pool contention. A contention measurement remains open for whoever next runs this method with a live pool.

**Steady-state wall-clock.** 57 real ticks recorded by the counter across this run (18 + 8 + a handful from setup verification, all against the same 113-node snapshot): `wall_ms` ranged 57-124, mean ~83ms. This is markedly higher than [[LC-520]]'s stale ~140ms-total/~115ms-`DoneUseCase` figures would suggest for a store this size, which is explained by the cProfile finding below - `DoneUseCase` was not, in fact, fully fixed by LC-520.

**RSS trend.** `rss_kb` rose from ~73-80MB over the first several ticks (process/import/cache warm-up) to a plateau around 88-89MB for the remainder of the run. No unbounded growth was observed over this run's length; a longer session (the brief's own "does memory grow over a long-running session" question) is not settled by 57 ticks over a few minutes and remains open.

**cProfile call-count finding.** Sorted by `ncalls` over an 8-tick cProfile run: `sqlite_store.py:608 _row_to_step` was called 40,167 times - roughly 2,200+ times per `_refresh()` tick, against a store of 113 nodes. Tracing callers: `done.py:61 _closed_items` (inside `DoneUseCase.execute()`, called once per tick from `_refresh_done_view`) drives `_rows_to_items`, which calls `_child_states_of` once per closed item (14 times/tick in this run) - and `_child_states_of` itself makes a `_row_to_step` call per child, repeated in full on every tick regardless of whether anything changed. `DoneUseCase.execute()` alone accounted for ~51% of a tick's total time in this profile (0.503s of 0.986s cumulative, across the 9 `_refresh()` calls this profile captured). This is the same call-count-explosion shape [[LC-520]] fixed in `get_item`, recurring in a different path (`DoneUseCase`/`_closed_items`/`_child_states_of`) that LC-520 did not touch. Not fixed here - recording it for [[LC-705]], per this item's own out-of-scope (below).

**`py-spy` in this environment.** `py-spy record --pid <pid>` requires root on macOS (`task_for_pid` is SIP-gated) and this measurement pass had no interactive path to grant it, so no flame graph was captured here. The commands above are runnable and unchanged by this; the deterministic `sort cumulative` view from the same cProfile run (not shown, since cProfile's own overhead distorts absolute time) corroborated `DoneUseCase.execute()` as the largest single contributor to a tick, consistent with the call-count finding above.

**Deferred findings.** This spec's own Deferred findings section names two further gaps this measurement run did not need to reprove by profiling - both found by reading `_refresh()`, not sampling it: `_refresh()` runs its full row-derivation work every tick regardless of whether the priority screen is the one on top of the screen stack, and the priority list's row-derivation runs unconditionally every tick even when the shape guard finds nothing changed. Acting on any of the three findings recorded in this document - the `DoneUseCase` call-count finding above, or either of the spec's own Deferred findings - is [[LC-705]]'s scope; this item changes no TUI behaviour beyond the gated counter.

## Results ([[LC-705]]'s post-fix measurement run, 2026-09-15)

**Setup.** Same method as the run above: a point-in-time copy of this machine's own live `~/.lightcycle/store.db`, taken via `sqlite3 .backup` (live store never opened for writing), loaded from an isolated `LC_HOME` - the live store itself was never pointed at directly. The live store had grown since the run above, to 459 items / 2280 steps at measurement time. `_refresh()` was driven directly via `TuiSession.poll_tick()`, the same harness the test suite uses, under an 8-tick `cProfile` run sorted by `ncalls` (never `cumulative`, per this doc's own method above).

**Before/after, same store snapshot, same method.** Measured by temporarily reverting `done.py`/`backlog.py` to their pre-fix content, running the identical script, then restoring the fix and re-running it - both passes against the exact same copied database, so the comparison isolates the code change:

|                                                       | pre-fix | post-fix |
| ----------------------------------------------------- | ------- | -------- |
| `_row_to_step` calls / tick                           | 4,602   | 2,320    |
| `DoneUseCase.execute()` share of `_refresh()` cumtime | 66.7%   | 48.2%    |

`_row_to_step` call volume roughly halved (49.6% reduction), matching the spec's synthetic benchmark's exact-halving prediction (Sources) and confirming the double-conversion diagnosis (Why) on real, current store data rather than only the synthetic one. `DoneUseCase.execute()` remains the largest single contributor to a tick - it was never claimed to stop being one, only to stop doing double the necessary `Step` conversion work - and the residual cost is now BacklogUseCase's mechanically identical pattern (also halved) plus the row-derivation work recorded as Deferred findings above, neither of which this item's Design touches (Out of scope).

**Not remeasured.** RSS trend, `py-spy`, and pool contention are unchanged by this item's Design (Out of scope) and were not rerun.

## Results ([[LC-729]]'s measurement run, 2026-09-17)

**Setup.** A fresh point-in-time copy of this machine's own live `~/.lightcycle/store.db`, taken via `sqlite3 .backup` (live store never opened for writing) plus a copy of `~/.lightcycle/workflows`, loaded from an isolated `LC_HOME` - the live store itself was never pointed at directly. The live store had grown again since [[LC-705]]'s run, to 513 items / 2671 steps at measurement time (counted directly on the copied file via `sqlite3`, not through the engine - see the worker-isolation note under Contention below for why). `tui-metrics: true` was set for the counter runs.

**The memory gate, checked at measurement time.** `~/.lightcycle/config` on this machine currently reads `memory-reserve-fraction: 0.65`, `suspend-pressure: 0.40`, `resume-pressure: 0.25`, `max-agents: 5` - meaningfully active, not neutered, unlike [[LC-705]]'s 2026-09-15 snapshot (`memory-reserve-fraction: 0`, `suspend-pressure: 0.99`). Read directly from the config file, not via `lc config` - this write-code pass runs under a worker role, which the CLI's own worker-permission gate does not allow to run `lc config`.

**Steady-state wall-clock and RSS, over a run materially longer than 57 or 720 ticks.** `_refresh()` was driven back-to-back via `TuiSession.poll_tick()` (no artificial delay between calls) against the snapshot above, for 2,000 ticks in ~206s of real compute time. A literal 2-hour, real-time-paced continuous session (the ~720-tick target) was not practical for this pass: this write-code step is a single ephemeral automated agent turn with a bounded compute budget, not a multi-hour interactive session. Substituting tick count for wall-clock duration is a deliberate choice, not an oversight - `_refresh()`'s own cost and CPython's memory/object-retention behaviour are both driven by how many times it is called, not by how much real time elapses between calls, so 2,000 back-to-back ticks (2.8x the ~720-tick target) exercise the "long session" question at least as hard as a spaced-out 2-hour run would, on the axis that actually matters here. A separate ~15-minute real-time-paced session was also attempted directly against a real `lc tui` process (not the harness) to corroborate at real terminal speed; that run is reported separately below because it was contaminated by an operational mistake and answers a narrower question.

`wall_ms`, excluding the first 20 ticks (warm-up): mean ~61ms, p50 53ms, p90 81ms, p99 178ms, occasional outliers up to 437ms. The outliers coincide with this machine genuinely running several other concurrent agents during the measurement window (visible in a real `lc tui`'s own priority list at the time - LC-746, LC-766, LC-738, LC-775 were all mid-flight); they are host contention, not this codebase's own cost, and py-spy/cProfile would not attribute them to `_refresh()` either.

`rss_kb` across the same 2,000 ticks: ~63-69MB for the first 100 ticks (past initial import/mount warm-up), climbing to ~90-96MB by ticks 1,700-2,000 and still rising, not plateaued. **This changes LC-527's own conclusion.** LC-527 observed a plateau around 88-89MB and reported "no unbounded growth... over this run's length", but only ran 57 ticks - long enough to _reach_ roughly the same 88-89MB level this run passes through around tick 900-1,000, not long enough to see that the climb continues past it. Run further to check whether growth is real rather than a measurement artifact: `gc.collect()` forced every 300 ticks across a separate 1,500-tick run neither reduced RSS nor found cyclic garbage (`gc.garbage` stayed empty each time), while `gc.get_objects()`'s own live-object count grew monotonically - 170,612 -> 216,791 -> 262,972 -> 309,143 -> 355,313 across the five checkpoints (~123 new _reachable_ objects retained per tick, not uncollected garbage awaiting a GC pass). A type-count diff between tick 200 and tick 700 of a separate run identifies where: `rich.segment.Segment` (+108/tick), plus exactly +1/tick each of `textual.events.Callback`, `asyncio.locks.Event`, `collections.deque`, `functools.partial`, `builtins.set`, and `textual.widget.PseudoClasses`. This is not either of the two already-known unbounded caches from [[LC-705]]'s Deferred findings (`_done_cost_time_cache`, `_report_cache`) - both are gated to only populate while their own view is visible, and this harness never switches views - so it is a new deferred finding (below), not a re-confirmation of an old one.

**Explicit answer: yes, RSS grows over a long session**, measurably and past the point LC-527 stopped looking, and the growth traces to reachable objects in the Textual/Rich rendering layer rather than to either named application-level cache.

**Real-terminal corroboration (contaminated - reported for what it can still show).** A real `lc tui` process (not the harness) was also run against the same snapshot for real-time-paced ticks. An earlier attempt at this same run, backgrounded and `disown`ed to survive past its own launching command, was not actually cleaned up when that command finished. It kept running unnoticed for the whole ~15 minutes that a second, deliberate attempt was then run alongside it. The resulting `run.log` interleaves two concurrent processes' samples throughout (visible as paired entries a few seconds apart at nearly every timestamp) with no PID recorded per line to de-multiplex them after the fact. Both strays were eventually found and killed via `pkill -f`, after `ps`/`pgrep` from the driving shell failed to show them at all (only `lsof`/`pkill` could see them - a sandboxing quirk of this environment worth knowing for whoever next tries this). Recorded here as a process-management mistake, not corrected retroactively: across the resulting 260 contaminated samples, `wall_ms` ranged 50-1,318ms (mean ~153ms - both processes competing for the same CPU, plus the same host contention noted above) and `rss_kb` ranged ~50-105MB. This is consistent in order of magnitude with the clean harness run above and confirms real ticks land every ~10s at real terminal speed, but it does **not** independently answer the single-process long-session RSS question - that answer rests on the clean 2,000-tick harness run above, not on this one.

**cProfile call-count finding.** A fresh 8+-tick `cProfile` run (9 ticks captured), against a separate copy of the same live store taken moments later (513 items / 2671 steps - store size did not change meaningfully between the two snapshots), driven the same way as [[LC-705]]'s run (`TuiSession`, sorted `ncalls`, never `cumulative`):

- `_refresh()` cumtime: 0.6263s over 9 ticks.
- `DoneUseCase.execute()` cumtime: 0.3085s - **49.3% of a tick**, up slightly from LC-705's post-fix 48.2%. Of that 0.3085s, 0.2856s (92.6%) is the single `all_items_including_done()` call inside `_closed_items()` - essentially all of what remains of `DoneUseCase`'s cost is exactly the cache-rebuild scan Why's premise expected, not some other, newly-exposed cost.
- `_row_to_step`: 27,090 calls over 9 ticks = 3,010/tick, up from LC-705's post-fix 2,320/tick - proportional to the store's growth (2,671 vs 2,280 steps, +17%; the call-count increase is somewhat above that, +30%, still well short of anything resembling the pre-fix doubling LC-705 fixed).
- **What is now the single largest contributor to a tick: still `DoneUseCase.execute()`, unambiguously, at 49.3%.** Nothing new stands out beneath it beyond what LC-705's own Deferred findings already named: `build_priority_rows` is next (0.1367s, 21.8%), then `_refresh_backlog_view`/`BacklogUseCase` (0.0865s, 13.8%) - the same priority-row-derivation and BacklogUseCase shape LC-705 already recorded as open, not a new subsystem this run promoted to visibility. This is the negative result Why's own "what does the profile look like now, as a whole" question anticipated as a legitimate answer.

**`py-spy` in this environment.** Still blocked, for the same reason as LC-527's run: `py-spy` is not even installed in this environment, and attaching to a real PID would additionally require root (`task_for_pid` is SIP-gated on macOS) - `sudo -n true` confirms no passwordless sudo is available to this non-interactive agent, and there is no interactive path to supply a password. No flame graph obtained.

**Contention reading against the real live pool: not taken by this pass, structurally.** This write-code step executes from a git worktree checkout. The engine's own `refuses_live_store` guard (LC-13.2) hard-refuses opening the real live store from any process rooted in a worktree, by design - this repo's own `CLAUDE.md` states the underlying rule plainly ("a worker cannot affect the pool that spawned it"). `tests.support.isolation.engine_lc_outside_any_worktree()` exists to route around the _worktree-package_ half of that check, but only for a test exercising a disposable live-_equivalent_ store, never the real one; using it against the actual live store here would defeat the exact safety boundary the guard exists to enforce, so it was not attempted. Taking this reading needs a human driver session running the normally-installed, non-worktree `lc`/`lc tui` against the live environment during a window with genuine pool activity, reading `pool_share` alongside `wall_ms`/`rss_kb` the way Design E describes. The memory-gate values recorded above (checked directly from the config file, which carries no such guard) are current as of this pass, 2026-09-17, for whoever takes that reading next to compare against rather than trust unchanged.

**Recommendation on [[LC-730]]: close it unbuilt.** `DoneUseCase`'s 49.3% share sounds large as a fraction, but in absolute terms it is ~30ms of CPU work once every 10-second tick - well under 1% of a single core - and that fraction barely moved (48.2% -> 49.3%) while the store it scans grew 17% (steps) since LC-705's run, so it is not a cost that compounds quickly on its own. The precedent Design F points to, `_done_cost_time_cache`, does not actually transfer: it caches a per-item _value_ keyed on a fact that cannot change once set (`item.closed_at`), while what LC-730 would need to cache is the _membership_ of the done set itself, which changes on every completion and, per [[LC-746]] (currently `queued`, unresolved as of this writing), on every reopen too - LC-746's items 2 and 4 are exactly the "a reopened item's rolled-up state" edge case a done-set cache would need to invalidate on correctly, and it is a live, currently-open bug in this exact area, not a hypothetical risk. Building a stateful cross-tick cache in a zone whose transition-detection is presently known-buggy, for a saving that is not user-perceptible, is not a good trade. If per-tick cost ever does become a real concern, [[LC-705]]'s own still-open Deferred finding - only running Done/Backlog derivation while their view is actually visible - is the cheaper lever to pull first, and does not carry a cross-tick invalidation problem at all.

**Delta against both prior runs.**

| Metric | LC-527 (2026-09-15) | LC-705 post-fix (2026-09-15) | LC-729 (2026-09-17) |
| --- | --- | --- | --- |
| Store size | 113 nodes | 459 items / 2280 steps | 513 items / 2671 steps |
| `wall_ms` mean | ~83ms (57-124 range) | not remeasured | ~61ms (50-437 range, warm) |
| `DoneUseCase.execute()` share of tick cumtime | ~51% | 48.2% | 49.3% |
| `_row_to_step` calls/tick | ~2,200+ (40,167/8 ticks) | 2,320 | 3,010 |
| RSS trend over the longest run taken | plateau ~88-89MB, 57 ticks, "no unbounded growth" | not remeasured | still climbing, ~90-96MB by tick 2,000 - LC-527's plateau reading superseded |
| `py-spy` | blocked (SIP/root) | not attempted | blocked (SIP/root, not installed) |
| Pool contention reading | not taken | not attempted | not taken (structurally blocked from a worktree - see above) |

**New deferred finding.** A Textual/Rich rendering-layer object population - `rich.segment.Segment` and, one each per tick, `textual.events.Callback`/`asyncio.locks.Event`/`collections.deque`/`functools.partial`/`builtins.set`/`textual.widget.PseudoClasses` - grows as live, reachable objects across ticks, confirmed by explicit `gc.collect()` not reclaiming them and by `gc.get_objects()`'s own count climbing linearly with tick count. Found while chasing this run's own RSS-trend question, via a headless harness run with no view ever switched away from the default, so it is neither of [[LC-705]]'s two already-known unbounded caches (`_done_cost_time_cache`, `_report_cache`), which don't populate under those conditions. Not diagnosed further or fixed here - this item's Design makes no source-code change - but worth a future item's attention if a long-running `lc tui` session's memory footprint ever becomes a real concern; the likely place to start is whatever per-tick call path constructs one of each of the six single-instance types above and does not release its reference (a `PriorityTable`/`DataTable` cell-update or style-resolution path is the most likely site, given `textual.widget.PseudoClasses` and the volume of `Segment`/style-related churn in the profile above).
