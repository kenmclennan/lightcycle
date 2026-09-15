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
