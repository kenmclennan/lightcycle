# Developing lightcycle

lightcycle builds itself, so this repo plays two roles: the **engine you run** (installed
via pipx) and the **source you develop** (this checkout). Keeping them separate is what
lets the running engine stay stable while you change its source.

**This is developer scaffolding - none of it ships in the tool.** A user of lightcycle
`pipx install`s it and `pipx upgrade`s it; they never build, "promote", or migrate an
engine. Commands and scripts in this doc exist only because lightcycle happens to be
developed here.

## Dev environment

```bash
bin/setup            # prerequisites check + dev venv (uv) + lc init + verify
bash tests/run.sh    # the full suite
```

The engine runs on system `python3` with zero runtime deps; `uv`/`pytest` are dev-only.

## Dogfood a change

Run the checkout directly so you exercise your in-progress code, not the installed engine:

```bash
python -m lightcycle.cli <cmd>         # or ./bin/lc <cmd>
LC_HOME=$(mktemp -d) ./bin/lc flow     # against a throwaway home, not your real ~/.lightcycle
```

Because lightcycle develops itself, a story filed with no `--repo` targets the engine's
own checkout under `projects/` - this is the self-hosting dev loop, not a product feature.

## Ship a change (promote)

1. Land it the normal way: branch, PR, review, merge to `main`.
2. Make the merged code your **running** engine:

   ```bash
   git checkout main && git pull
   bin/promote-engine       # pipx install --force the checkout
   ```

`bin/promote-engine` installs the current checkout as the pipx-managed `lc`. Because the
running engine only changes when you deliberately promote, `lc start` never picks up
half-finished engine changes mid-flight. Rollback is just checking out the previous ref
and re-running the script.

There is intentionally **no `lc promote` / `lc rollback` command** - promoting a
self-built engine is a dev workflow, not a feature of the shipped tool.
