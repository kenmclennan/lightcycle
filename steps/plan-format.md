# Plan document format

The plan doc is the review surface for a decomposition. It must be falsifiable
in a single reading: decisions, a DAG, and a task table. Narrative is a one-line
summary only.

## Sections (in order)

### Summary

One sentence: what the epic builds and why. No prose beyond that.

### Scope

A mermaid diagram showing the relationship between epic -> planner ->
review gate -> child stories -> PRs, plus any sibling blocked-by edges.
One-line caption below the diagram.

### Decisions

| Chose | Over | Because |
| ----- | ---- | ------- |

One row per non-obvious choice. "Chose" is the thing you picked; "Over" is what
you rejected; "Because" is the falsifiable reason.

### Out of scope

| Deferred | Why |
| -------- | --- |

Explicit deferrals only - things that could be confused for in-scope.

### Build tasks

Dependency diagram (mermaid graph LR) showing which child stories block which.

| #   | Task | Blocked by | Spec | Size |
| --- | ---- | ---------- | ---- | ---- |

Size: XS / S / M / L. Spec is the absolute path to the child's spec file.

### Assumptions

| Assumption | Source |
| ---------- | ------ |

Every assumption you made where the brief was silent. A long assumptions list
is a signal to the reviewer that the brief was thin - catch it here before work
starts.

### Risks

Brief bullets only. Build agents read their own child spec, not this doc, so
risks here are for the reviewer's eyes only.

## Style rules

- Hyphens, not emdashes.
- Format with `npx prettier --write` before linking.
- The reviewer reads the decisions and DAG; keep narrative short.
- "Create children first, gate last" - avoid gate-without-children orphans.
