# lightcycle: usage

`lc` is the front door. tmux is optional - run the parts in whatever terminals you
like.

## Start working

```bash
lc init          # one-time: create the lightcycle store for this project
```

Then run the parts in separate terminals:

```bash
lc start           # the loop (foreground; shows activity live). Ctrl-C to stop.
lc driver        # your interactive seat
```

## See what's happening

```bash
lc status              # inbox / active / queue / blocked
lc inbox               # what needs YOU now (gates + blocks)
lc backlog             # backlog items to develop later
lc active              # what agents are working now
lc queue 10            # next 10 upcoming agent tasks
lc ps                  # running workers: role, task, pid, alive/dead
lc logs run -f         # tail the run-loop
lc logs <task> -f      # tail the worker on a task
lc logs coder -f       # tail the most recent coder
lc show <task>         # one task incl. resume-state (for escalations)
```

## Drive work in

In the driver, shape a spec with the human, then:

```bash
lc file specs/<id>.md --step build  # enters it into the pipeline at the build step
```

The run-loop spawns a coder within a tick; it claims, builds, and exits, then the
flow advances to review, then open-pr. `for:human` items (escalations, PRs ready to
merge) show up in `lc inbox`.

## Recover after a kill

```bash
lc sweep   # release any orphaned claims (dead worker -> task reclaimable)
```

The run-loop runs this each tick, so dead workers self-heal. Kill-and-restart is a
first-class operation.

## glow spec render

`bin/lc-spec.sh <id>` renders a spec with glow (run with no args to list specs).
