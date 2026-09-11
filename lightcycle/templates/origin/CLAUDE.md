# CLAUDE.md - %s

A **workflow origin**: a pullable `lc` source. `source.toml` names it and declares the engine contract it targets; `workflows/*.md` are graphs (`entry`/`requires`/`workspace`/`phase`/`nodes`/`edges`/`hooks`/`signals`); `steps/*.md` are the agent role prompts a graph's stages reference. `lc workflow add`/`upgrade` pulls this repo into an immutable, sha-pinned bundle; each item then pins one `<origin>/<name>@<sha>`.

## The self-contained-bundle rule

A workflow in this repo may reference only step files inside this same repo (`steps/*.md`) - never a file in another origin, and never the `lc` engine's own `lightcycle/prompts/` (those are the engine's own driver/audit prompts, not workflow content). A bundle that reaches outside itself is not portable: `lc workflow add` pins a single sha, so an external reference resolves against whatever that other location happened to contain at pull time, or nothing at all.

## Building a workflow here

Author with the `lightcycle:author-workflow` skill. If this origin has no workflow yet, bootstrap the first one with a generic pipeline (e.g. `spec-driven`) pointed at this repo, the same way `lightcycle-workflows` bootstrapped its own `workflow-authoring` workflow. Model a new graph and its step prompts on bundles already pulled from the `lightcycle` origin (`spec-driven`, `bdd-driven`, `workflow-authoring`) - never on the engine source (`lightcycle/prompts/driver.md` and its neighbors are the engine's own prompts, not a workflow template).

## The gate is the simulator, not a test suite

`lc workflow check <origin>/<name>` (static composition) and the `simulate` CI job (`.github/workflows/simulate.yml`) are what a PR touching `workflows/*.md` or `steps/*.md` must pass. That gate installs the engine at `ENGINE_PIN`, which starts as `main` - set it to a SHA you have watched pass every bundle here, so a PR's result depends only on its own diff. The nightly run always tracks the engine's `main`, so upstream drift surfaces as a scheduled failure rather than as a false `ci-failed` rework on an unrelated PR. `lc workflow describe <origin>/<name> --mermaid` renders the built graph so a reviewer can confirm it matches the design.

## Style

Format every file with `npx prettier --write` **except** `workflows/*.md` - its `entry`/`requires`/`workspace`/`phase`/`nodes`/`edges`/`hooks`/`signals` blocks are a structured graph grammar, not prose, and prettier's markdown formatter reflows them.
