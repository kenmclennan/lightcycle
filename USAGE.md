# the-grid: usage

`tg` is the front door. tmux is optional - run the parts in whatever terminals you
like.

## Start working

```bash
tg init          # one-time: create the grid store for this project
```

Then run the parts in separate terminals:

```bash
tg run           # the loop (foreground; shows activity live). Ctrl-C to stop.
tg driver        # your interactive seat
```

## See what's happening

```bash
tg status              # mine / active / queue / blocked
tg mine                # what needs YOU (for:human)
tg active              # what agents are working now
tg queue 10            # next 10 upcoming agent tasks
tg ps                  # running workers: role, bead, pid, alive/dead
tg logs run -f         # tail the run-loop
tg logs <task> -f      # tail the worker on a task
tg logs coder -f       # tail the most recent coder
tg show <task>         # one task incl. resume-state (for escalations)
```

## Drive work in

In the driver, shape a spec with the human, then:

```bash
tg file specs/<id>.md --step build  # enters it into the pipeline at the build step
```

The run-loop spawns a coder within a tick; it claims, builds, and exits, then the
flow advances to review, then open-pr. `for:human` items (escalations, PRs ready to
merge) show up in `tg mine`.

## Recover after a kill

```bash
tg sweep   # release any orphaned claims (dead worker -> task reclaimable)
```

The run-loop runs this each tick, so dead workers self-heal. Kill-and-restart is a
first-class operation.

## glow spec render

`bin/grid-spec.sh <id>` renders a spec with glow (run with no args to list specs).
