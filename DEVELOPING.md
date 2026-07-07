# Developing the-grid

the-grid builds itself, so this repo plays two roles: the **engine you run** (installed
via pipx) and the **source you develop** (this checkout). Keeping them separate is what
lets the running engine stay stable while you change its source.

**This is developer scaffolding - none of it ships in the tool.** A user of the-grid
`pipx install`s it and `pipx upgrade`s it; they never build, "promote", or migrate an
engine. Commands and scripts in this doc exist only because the-grid happens to be
developed here.

## Dev environment

```bash
bin/setup            # prerequisites check + dev venv (uv) + tg init + verify
bash tests/run.sh    # the full suite
```

The engine runs on system `python3` with zero runtime deps; `uv`/`pytest` are dev-only.

## Dogfood a change

Run the checkout directly so you exercise your in-progress code, not the installed engine:

```bash
python -m the_grid.cli <cmd>          # or ./bin/tg <cmd>
GRID_HOME=$(mktemp -d) ./bin/tg flow  # against a throwaway home, not your real ~/.grid
```

## Ship a change (promote)

1. Land it the normal way: branch, PR, review, merge to `main`.
2. Make the merged code your **running** engine:

   ```bash
   git checkout main && git pull
   bin/promote-engine       # pipx install --force the checkout
   ```

`bin/promote-engine` installs the current checkout as the pipx-managed `tg`. Because the
running engine only changes when you deliberately promote, `tg run` never picks up
half-finished engine changes mid-flight. Rollback is just checking out the previous ref
and re-running the script.

There is intentionally **no `tg promote` / `tg rollback` command** - promoting a
self-built engine is a dev workflow, not a feature of the shipped tool.

## The one-time layout migration

`tg migrate` is a **transitional** command: it moves an old clone-and-run layout (a
`~/.config/the-grid/config` and an in-repo `.grid.db`) into `~/.grid`, backing the store
up first. It exists only for machines that predate the package; fresh installs never need
it, and it is slated for removal once existing machines are migrated (backlog `tg-14`).
