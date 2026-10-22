# The TUI

`lc tui` opens an interactive dashboard over the same store the CLI reads. It shows two kinds of screen: a **priority list** of work and a **node hub** for one item or step. This document describes the model those screens present. It is not a keybinding reference - the footer renders the bindings for whatever screen you are on, and a duplicated list here would be the copy that goes stale.

Where `tests/feature/the-*-tab.feature` and `tests/feature/priority-list-renders-current-work.feature` state behaviour exactly, this document says what the shape is and lets the scenarios hold the detail, the way [data-model.md](data-model.md) does for the store.

## Screens

**The priority list** answers "what is happening, and what needs me". Its tab strip reads `Current work · Backlog · Done · Report · Automation`; the dashboard lands on Current work, and `[` from there wraps to Automation. Backlog, Done, Report and Automation are the other views alongside Current work.

Current work is three fixed-order groups - needs-attention, active, queued - with one row per **item**, never per step. A row carries the item's id, its project, its title, the stage of its current or next step, and for active work a live approximate elapsed time. A terminal bell rings the moment something newly enters needs-attention, so it can be noticed in an unfocused pane, and never rings again for the same item while it stays there. An engine step such as CI polling only runs on a pool tick, so it counts as active, with the animated glyph, only while the pool is running; with the pool stopped it shows as queued.

**The node hub** answers "what is the state of this one thing". It opens for a single node and its tab strip is type-aware.

## Prose panes

**Headings and wiki-links.** One renderer serves the item hub's Description tab. A `#`-to-`######` line renders as a heading with the markers removed, in `HEADING_STYLE` (bold cyan) - the same style used for other headings in the dashboard. Lines inside a fenced block and `#hashtag` stay literal. `[[ID]]` resolves to `Title (ID)` with the parenthesised id dim; an id that resolves to nothing reads `ID (not found)`. Hub refreshes include the resolved titles, so a renamed item repaints without its referencing description changing.

The CLI deliberately does not do this: `lc show` emits the stored description as JSON, raw.

## The item/step split

A node is an item or a step, and each has its own tabs:

|      | tabs, in order                       |
| ---- | ------------------------------------ |
| item | Description, Outputs, Workflow, Cost |
| step | Detail, Context, Workflow, Log, Cost |

Workflow and Cost appear on both. A step has no Description or Artifacts tab: its Detail and Context tabs read the step's own resolved `detail` list and its inputs, outputs and records. That is not a violation of the rule that no tab reaches across the item/step boundary for content: each renders **the node the hub is open for**, and the rule is about content, not about which tabs exist. It is why the redirect helpers were deleted - a tab never silently shows you a different node's data.

There is no Hierarchy tab. The tree view is the Workflow tab.

## The landing rule

Three lines, and worth stating because it is the one piece of hub behaviour that is not visible from the screen itself:

- An **item** lands on Description.
- A **step** lands on **Log** while its worker is running, on the Detail entry a waiting gate `presents`, on its parked `reason`, and otherwise on the first Detail entry with a value; a done step with a PR lands on `pr`, and one with outputs lands on the first output in Context. When no Detail entry has a value it falls to Context, and when Context is empty to Workflow, so a landing never targets an empty tab.

A running step's log is the only thing changing, so that is where the hub puts you. Once it stops, the entry the step exists to show is what you want.

## What Detail carries

Detail renders the engine's resolved `detail` list for the step, in order, and the TUI keeps no field list of its own. A step that declares `detail:` shows exactly those entries; one that does not gets the default list (`outcome`, `report`, plus `pr` when it has a run), led by the entry a legacy `presents` names (`pr`, `in:description` or `in:<name>`). A parked step's Detail always leads with `reason` and `needs`, whatever the step declares. A value that contains a newline or is longer than 80 characters is a **block**: its key on one row and the body beneath it, rendered with headings and `[[ID]]` references. Any other value is a **line**, key and value on one row. A declared entry with no value stays listed, blank; when every entry is blank the tab says so instead of showing an empty table.

Selecting `pr` opens it in the browser and `worktree` in the configured editor (`lc config`'s `editor` key). Any other entry whose value is a single `http://` or `https://` URL opens in the browser too; other entries open nothing.

## What Context carries

Context is one table with three sections. **Inputs** are the step's frozen inputs (titled `INPUTS (live, not yet frozen)` while the step is still open). **Outputs** are what this step produced, led by its `report`. **Records** are what it left behind that is not an output: its reflection and the guidance it was delivered, skipped and cited. Context has two columns, key and value. A pass-scoped row shows its pass in the key, as `report (p1)`. Values render as prose, the way the Detail tab renders a block field: paragraphs, lists and headings are kept, `[[ID]]` references resolve to titles, and a bare URL or `[label](url)` is a clickable link. Selecting a row opens a `url` in the browser and a `filepath` in the editor; text and list rows have nothing to open because their value is already readable in place.

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

The footer carries its own set for pool and Claude availability: `●`/`○` for the pool running or stopped, `◑` amber for a draining pool (`pool draining (N workers, M engine steps)`, with ` - slow` appended once the drain has waited past the bound; the `p` prompt offers "Drain: finish running work, then stop" while the pool runs and is not already draining), `●`/`⊘`/`◐` for Claude available, unavailable or being probed, `⬆` amber when an engine upgrade is available, and `↻` amber when the config file has been edited since the TUI launched (restart to apply). <!-- markdownlint-disable-line MD038 -->

Colour is doing one job in that table: amber means you, red means you urgently, cyan means moving, dim means neither.
