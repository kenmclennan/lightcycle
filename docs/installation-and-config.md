# Installation, config, and upgrades

## Install

```
pipx install git+https://github.com/kenmclennan/lightcycle
lc init                 # create the store + seed the home config (run once)
```

The engine runs on system `python3` with zero runtime dependencies, so `lc` works without any venv activation.

## The homes

lightcycle keeps code, data, and pulled workflows strictly apart. This split is what makes upgrades safe.

```mermaid
graph TD
  subgraph engine[ENGINE - the pipx venv, REPLACED by an upgrade]
    code[lightcycle code]
    prompts[prompts - steps/audit.md, steps/daily-summary.md]
  end
  subgraph data[DATA - your home dir, NEVER touched by an upgrade]
    store[store.db]
    conf[config]
    wf[pulled workflow bundles - origin/sha]
    rest[logs and worktrees and backups and the run lock]
  end
  subgraph projects[PROJECTS - your repos]
    repo[project working tree]
    reg[registered in the project registry - identity, shortcode, local path]
  end
```

- **Engine** (`~/.local/pipx/venvs/lightcycle`) - the code plus `prompts/` (the engine-owned agent prompts it spawns directly: `prompts/steps/audit.md`, `prompts/steps/daily-summary.md`). This is the only thing an upgrade changes; the engine ships no workflow library.
- **Data** (`~/.lightcycle`, the `data_root`) - `store.db`, the `config` file, `logs/`, `.worktrees/` (isolated per-item checkouts), `backups/`, the `.lc-run.pid` singleton lock, and `workflows/<origin>/<sha>/` (the immutable, sha-pinned workflow bundles pulled from origins).
- **Projects** - your repos, wherever they live. Each is named to lightcycle by registering it (`lc project add <owner/name> [--shortcode X] [--path P]`); the registry holds the identity, the shortcode ids are minted from, and the local path. A project carries no lightcycle config of its own, and there is no step or workflow override. `lc init` registers one project automatically, under the identity `specs` (defaulting to `~/workspace/specs`) - the `workspace: specs` value a spec-driven workflow declares resolves through this same registry entry, not a dedicated config key.

Workflows are not shadowed or resolved through a chain: each item pins one sha-pinned bundle (`<origin>/<name>@<sha>`) and the loader reads the flow and steps from that pin. `LC_HOME` names the data home (the store); the integration tests point it at a throwaway store. Never run against the live store by hand.

## Config

`~/.lightcycle/config` is the single boundary to the environment. Values are required and seeded visibly (no hidden defaults). Show or edit with `lc config [--edit]`.

The file is read **once per process**, not per lookup, so a long-running process keeps the values it started with: editing `max-agents` while `lc start` is running changes nothing until the pool is restarted. This is deliberate - a config re-read mid-operation would apply to some of an operation and not the rest, depending on call order. Short-lived commands (`lc show`, `lc done`) pick up an edit on their next invocation.

This table documents every `_SEED_KEYS` entry - `tests/unit/test_docs_reference_real_things.py` fails the build if a key is added without a row here. The twelve `price-*-per-mtok` keys are documented as one row, keyed by the pattern `price-<model>-<kind>-per-mtok`, rather than individually.

| key | meaning |
| --- | --- |
| `projects` | root under which project repos live |
| `shortcode` | id prefix for new top-level nodes (e.g. `LC` gives `LC-1`) |
| `default-origin` | the workflow origin the spawner reads step prompts from. There is **no default workflow**: activation requires the item to carry `--workflow <origin>/<name>` |
| `workflows-remote` | git remote for the built-in workflow origin. Seeded blank; `lc init` only pulls it once set (`lc config --edit`, then `lc workflow add <url> --name <origin>`) |
| `workflow-retention` | pulled bundles kept per origin (plus any a live item pins) |
| `max-agents` | worker cap the pool fills to each tick; must be `>= 0` (`0` pauses admission for the tick) |
| `poll-seconds` | pool tick interval |
| `branch-prefix` | prefix for worktree branches |
| `max-boot-seconds` / `max-session-seconds` | worker boot and session caps; both must be `>= 0` |
| `stall-seconds` | how long a claimed worker's log can go without growing before the pool kills it and reclaims its step; must be `>= 0` |
| `probe-cooldown-seconds` | how long the breaker waits before allowing another probe after the previous one stalled; must be `>= 0` |
| `spin-cap` | consecutive no-work worker deaths, on one step or pool-wide, before the pool parks the step / caps itself to one worker |
| `retro-interval-reflections` | reflections pending across un-retroed items and un-retroed closed passes of items still open, between engine retro audits |
| `daily-summary-debounce-seconds` | how long a day must sit with uncaptured closed-item activity before the engine spawns a fresh daily-summary agent |
| `backups-dir` / `backup-interval-minutes` / `backup-retention` | store snapshot location, cadence, and retention |
| `max-title-length` | cap on an item's title; `lc new`/`lc set` refuse a longer one outright rather than truncating, so detail belongs in `--description`. A step has no title of its own - it is composed at render time from its stage and its item's title - so this cap does not apply to one |
| `worktree-retries` / `worktree-retry-sleep` / `worker-history` / `editor` | pool + tooling knobs |
| `shutdown-grace-seconds` | how long `lc start`'s shutdown waits for killed workers to be reaped before sweeping; must be `>= 0` |
| `tick-failure-cap` | consecutive tick exceptions the pool loop tolerates (logging and continuing) before it re-raises and exits non-gracefully |
| `personal-origin` | the user's own workflow-origin repo, set by `lc workflow init`. Optional - unset (empty) until one exists |
| `context-artifact-types` | artifact types an agent step resolves to a repo-relative file path (e.g. `spec`). Optional - soft-defaults to `spec` if unset |
| `internal-shortcode` | id prefix for items the engine creates for itself (e.g. retro-cadence audit items) - distinct from `shortcode`, which prefixes items you create |
| `memory-reserve-fraction` | fraction of machine memory headroom the pool always withholds from worker admission; must be in `[0, 1]` |
| `suspend-pressure` | threshold above which the memory gate signals a running worker to suspend, checked against whichever is greater of the pool's own memory share and the machine's overall memory pressure; the same combined signal also withholds new worker admission whenever it is already at or above this threshold, so a newly admitted worker is not immediately suspended; must be in `[0, 1]` |
| `resume-pressure` | threshold below which the memory gate signals a suspended worker to resume, checked against the same combined signal as `suspend-pressure`; must be set strictly below `suspend-pressure`, and must itself be in `[0, 1]` |
| `review-rounds-cap` | consecutive review-reject rounds on one step a workflow's review-rounds-cap transition tolerates before it fires |
| `tui-autostart-pool` | whether the TUI starts the pool loop automatically on launch |
| `tui-metrics` | whether the TUI records its own per-tick refresh timing to the run log |
| `tui-upgrade-check-seconds` | how often the TUI rechecks for a new engine version in the background; `0` disables the periodic recheck (the check still runs once on launch); must be `>= 0` |
| `pool-upgrade-check-seconds` | how often `lc start`'s pool loop rechecks for a new engine version while running; `0` disables the periodic recheck (the check still runs once at startup); must be `>= 0` |
| `price-<model>-<kind>-per-mtok` | per-million-token USD pricing used for usage cost reporting, one key per `<model>` (`sonnet`/`opus`/`haiku`) x `<kind>` (`input`/`output`/`cache-write`/`cache-read`) - twelve keys total, defaults in `config.py`'s `_SEED_KEYS`; each must be `>= 0` |

## Workflow sources

Workflows come from pullable git **origins**, not the engine. `lc init` pulls the built-in `lightcycle` origin (from `workflows-remote`) into an immutable, sha-pinned bundle under `~/.lightcycle/workflows/<origin>/<sha>/`. Manage them with:

```
lc workflow init <name>       # scaffold + register a personal workflow-origin repo
lc workflow add <url>         # register + pull an origin
lc workflow upgrade <origin>  # pull the latest, re-pin
lc workflow list              # origins + on-disk bundle paths
lc workflow rm <origin>
```

Each item pins `<origin>/<name>@<sha>` at activation, and the loader resolves its flow and steps from that pin. A project customises its workflow by authoring its own source (see the `author-workflow` skill in the plugin), not by dropping override files anywhere. A project's `shortcode` is set when it is registered: `lc project add <owner/name> --shortcode X`.

## Upgrades

```
lc upgrade            # check remote version, upgrade in place if newer
lc upgrade --check    # report only, do not install
```

`lc upgrade` compares the installed `__version__` against the version on the repo's `main`, and if newer runs `UV_VENV_CLEAR=1 pipx install --force git+...` (the `UV_VENV_CLEAR=1` is required when pipx uses the `uv` backend, which otherwise refuses to overwrite the existing venv).

What an upgrade **changes**: the engine venv (code + `prompts/`). What it **does not touch**: `~/.lightcycle` - your store, config, logs, worktrees, pulled workflow bundles, and the project registry. Your data and pulled workflows survive every upgrade; workflows are updated separately with `lc workflow upgrade`.

Schema changes are handled separately: when a new engine first opens a store written by an older schema, it **backs the store up** (gzipped, into `~/.lightcycle/backups/`) and migrates in place. Migrations are idempotent. Stop the pool loop before upgrading, so the old engine is not running against a newly-migrated store; restart it after.
