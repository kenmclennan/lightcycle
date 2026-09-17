# The TUI

`lc tui` opens an interactive dashboard over the same store the CLI reads. It shows two screens: a **priority list** of work, and a **node hub** for one item or step. This document describes the model those screens present. It is not a keybinding reference - the footer renders the bindings for whatever screen you are on, and a duplicated list here would be the copy that goes stale.

Where `tests/feature/the-*-tab.feature` and `tests/feature/priority-list-renders-current-work.feature` state behaviour exactly, this document says what the shape is and lets the scenarios hold the detail, the way [data-model.md](data-model.md) does for the store.

## Two screens

**The priority list** answers "what is happening, and what needs me". It has a Current work view and a Backlog view.

Current work is three fixed-order groups - needs-attention, active, queued - with one row per **item**, never per step. A row carries the item's id, its project, its title, the stage of its current or next step, and for active work a live approximate elapsed time. A terminal bell rings the moment something newly enters needs-attention, so it can be noticed in an unfocused pane, and never rings again for the same item while it stays there.

**The node hub** answers "what is the state of this one thing". It opens for a single node and its tab strip is type-aware.

## The item/step split

A node is an item or a step, and each has its own tabs:

|      | tabs, in order                         |
| ---- | -------------------------------------- |
| item | Description, Workflow, Artifacts, Cost |
| step | Detail, Workflow, Log, Cost            |

Workflow and Cost appear on both. That is not a violation of the rule that no tab reaches across the item/step boundary for content: each renders **the node the hub is open for**, and the rule is about content, not about which tabs exist. It is why the redirect helpers were deleted - a tab never silently shows you a different node's data.

There is no Hierarchy tab. The tree view is the Workflow tab.

## The landing rule

Three lines, and worth stating because it is the one piece of hub behaviour that is not visible from the screen itself:

- An **item** lands on Description.
- A **step** lands on **Log** while its worker is running, and on **Detail** otherwise.

A running step's log is the only thing changing, so that is where the hub puts you. Once it stops, Detail is what you want.

## What Detail carries

Detail is a field list, in a fixed order, showing only fields that have a value. PR and branch lead it.

They lead it because they are what you reach for when a step is in trouble, and they are unambiguous from where the reader stands: a step belongs to exactly one phase run, and that run owns exactly one branch and one PR. The store normalises that - the PR lives on the phase run, not the step - and the view denormalises it back. The reader never has to know the difference.

Right after branch comes worktree, when its repo can be resolved: the local checkout that branch actually lives in, derived rather than stored. Selecting it opens it in the configured editor (`lc config`'s `editor` key) rather than a browser - reviewing a build means being in that checkout, not just looking at its PR.

After PR, branch and worktree: stage, state, role, model, claimed_by, outcome, notes, then a parked step's needs, reason and tried, then its reflections.

A step can carry **more than one reflection** - they are artifacts, not a column, and a step that ran several times accumulates several. The first renders as `REFLECTION`; subsequent ones as `REFLECTION` under keys `reflection:2`, `reflection:3` and so on, so each is shown rather than the rest being silently dropped.

## The Workflow tab

The whole tree from the node's item down, always fully expanded, never collapsed. Every row shows its own real id and its state in the same glyph and colour vocabulary as the priority list.

A step always renders one level below its item - never a pass row, never a second level of nesting. A step's label carries its phase, and its pass number whenever its item has run more than one pass.

The node the hub is open for is highlighted wherever it falls. As you scroll past its parent item, that item's row stays pinned to the top, so context is never lost. Enter or the right arrow opens whatever is highlighted into its own hub.

## Roles, and what the TUI does with them

A step's role is `agent`, `human`, or `engine`.

- **agent** - a worker is spawned for it. It has a log.
- **human** - it waits for you. It has no log, and it draws a hollow square in place of the ordinary hollow-circle glyph when done or queued. A live gate or escalation is already distinguishable by its own amber or red glyph, so the square never applies there.
- **engine** - the engine performs it on its own tick. No worker is ever spawned, so it has no log, no wall-clock, no token cost, and no "pool halted" state - the pool's capacity is irrelevant to it. `poll-ci` is the first stage to use this role.

An engine-owned step is never in your inbox. Inbox membership means a step is `waiting`, and `waiting` means a human must act; an engine-owned step derives `queued`, because something else will act. It is visible as in-flight work everywhere else.

## The escalation banner

A parked step's escalation shows in the hub **header**, not in a tab. It has to be visible on every tab and alongside the list rows, and a tab can be switched away from.

## Glyphs and colour

One vocabulary, shared by the priority list and the Workflow tab.

| glyph     | meaning                                                   |
| --------- | --------------------------------------------------------- |
| `●` amber | a gate - waiting for you                                  |
| `▲` red   | an escalation - a step parked for a decision              |
| `◆` cyan  | active; it animates through `◇ ◈ ◆ ◈` while a worker runs, or while an engine-owned step is in flight |
| `○` dim   | queued, or done                                           |
| `□` dim   | a human-role step, done or queued                         |
| `⊣` dim   | held by a dependency, drawn alongside the state glyph     |

The footer carries its own set for pool and Claude availability: `●`/`○` for the pool running or stopped, `●`/`⊘`/`◐` for Claude available, unavailable or being probed, and `⬆` amber when an engine upgrade is available.

Colour is doing one job in that table: amber means you, red means you urgently, cyan means moving, dim means neither.
