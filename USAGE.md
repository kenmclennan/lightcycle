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
lc queue 10            # next 10 upcoming agent steps
lc ps                  # running workers: role, step, pid, alive/dead
lc logs run -f         # tail the run-loop
lc logs <step> -f      # tail the worker on a step
lc logs coder -f       # tail the most recent coder
lc show <step>         # one step incl. resume-state (for escalations)
```

## Drive work in

In the driver, shape a spec with the human, then:

```bash
lc new item "<title>" --parent <theme>  # then: lc attach <item> spec <path>; lc set <item> --state active
```

The run-loop spawns a coder within a tick; it claims, builds, and exits, then the
flow advances to review, then open-pr. `for:human` items (escalations, PRs ready to
merge) show up in `lc inbox`.

## Recover after a kill

```bash
lc sweep   # release any orphaned claims (dead worker -> step reclaimable)
```

The run-loop runs this each tick, so dead workers self-heal. Kill-and-restart is a
first-class operation.

## glow spec render

`bin/lc-spec.sh <id>` renders a spec with glow (run with no args to list specs).
