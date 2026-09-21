# The TUI

`lc tui` opens an interactive dashboard over the same store the CLI reads. It shows three kinds of screen: a **priority list** of work, a **node hub** for one item or step, and a **goal hub** for one goal. This document describes the model those screens present. It is not a keybinding reference - the footer renders the bindings for whatever screen you are on, and a duplicated list here would be the copy that goes stale.

Where `tests/feature/the-*-tab.feature` and `tests/feature/priority-list-renders-current-work.feature` state behaviour exactly, this document says what the shape is and lets the scenarios hold the detail, the way [data-model.md](data-model.md) does for the store.

## Screens

**The priority list** answers "what is happening, and what needs me". Its tab strip reads `Goals · Current work · Backlog · Done · Report · Automation`; the dashboard lands on Current work, and `[` from there reaches Goals. Goals, Backlog, Done, Report and Automation are the other views alongside Current work.

Current work is three fixed-order groups - needs-attention, active, queued - with one row per **item**, never per step. A row carries the item's id, its project, its title, the stage of its current or next step, and for active work a live approximate elapsed time. A terminal bell rings the moment something newly enters needs-attention, so it can be noticed in an unfocused pane, and never rings again for the same item while it stays there.

**The node hub** answers "what is the state of this one thing". It opens for a single node and its tab strip is type-aware.

## Goals

The Goals tab is a one-column table of goal titles - no status, count, icon or badge. Selecting a goal opens a **goal hub**, a separate screen class from the node hub because a goal is not a node. It reuses the hub's tab strip and the description pane's shape and closes with escape or left. Its tabs, in order:

- **Overview** - the goal's description as one scrolling document with headings and wiki-links rendered (see below). The header line above the tab strip carries the title, the hand-set status and the project; the goal id is a CLI handle and is not shown.
- **Log** - the goal's decisions, newest first. Each entry is a header line (title left, in the shared heading style on every wrapped line, timestamp right-aligned as `YYYY-MM-DD HH:MM`), a blank line, the body, and a blank line. A `SEARCH` row above the log (focused with `/`) filters entries by a case-insensitive substring of title or body; it appears only when the goal has entries.
- **Items** - linked items in three groups under headers in the shared heading style, in this order: `CURRENT WORK`, `BACKLOG`, `DONE` (an empty group has no header, and the cursor never rests on a header). Current work rows carry the same glyph, dependency glyph and step text Current work shows for the item, the step text right-aligned on its own line under a wrapping title; backlog and done rows are id and title only. Membership is never re-derived here: Current work uses `select_priority_rows`, Backlog `is_backlogged_item`, Done `is_closed_item` (the predicates `BacklogUseCase` and `DoneUseCase` call), and the suspended glyph reads `suspended_step_ids`, the same set the app uses. An open item that is in no lane and not backlog-shaped (its only live step is watched) is listed under Current work with no step text. Enter or right opens the item's hub (the step's hub for a Current work row that has a step). A `SEARCH` row above the list (focused with `/`) filters all three groups by id, title, project or repo, and appears only when the goal has linked items.

**Headings and wiki-links.** One renderer serves every prose pane: the item hub's Description tab, the goal Overview description, and each goal Log entry body. A `#`-to-`######` line renders as a heading with the markers removed, in `HEADING_STYLE` (bold cyan) - the same style as Log titles, and the Items group headers. Lines inside a fenced block and `#hashtag` stay literal. `[[ID]]` resolves to `Title (ID)` with the parenthesised id dim; an id that resolves to nothing reads `ID (not found)`. Hub refreshes include the resolved titles, so a renamed item repaints without its referencing description changing.

The CLI deliberately does not do this: `lc show` emits the stored description as JSON and `lc goal show` prints the source text the driver edits with `lc goal set --description`, both raw.

The hub refreshes on the same poll interval as the node hub, so `lc goal log` in another terminal appears without reopening it.

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

| glyph | meaning |
| --- | --- |
| `●` amber | a gate - waiting for you |
| `▲` red | an escalation - a step parked for a decision |
| `◆` cyan | active; it animates through `◇ ◈ ◆ ◈` while a worker runs, or while an engine-owned step is in flight |
| `○` dim | queued, or done |
| `□` dim | a human-role step, done or queued |
| `⊣` dim | held by a dependency, drawn alongside the state glyph |

The footer carries its own set for pool and Claude availability: `●`/`○` for the pool running or stopped, `●`/`⊘`/`◐` for Claude available, unavailable or being probed, and `⬆` amber when an engine upgrade is available.

Colour is doing one job in that table: amber means you, red means you urgently, cyan means moving, dim means neither.
