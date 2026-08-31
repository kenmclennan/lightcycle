Feature: Priority list renders current work
  The priority list shows needs-attention, active and queued work as three
  fixed-order groups, each row carrying its owning project, its current or
  next step, and - for active work - a live approximate elapsed time. A
  terminal bell rings the moment something newly enters needs-attention, so
  it can be noticed even in an unfocused pane, and never rings again for the
  same item while it stays there.

  Scenario: Needs-attention items are grouped above active and queued work, with their own icon and colour
    Given the store has a step in the inbox lane, an active step, and a queued step
    When I launch the dashboard
    Then the inbox step's row is grouped above the active and queued groups
    And the inbox step's row is shown with its own icon and colour, distinct from the active and queued rows

  Scenario: A dependency-held step is grouped with queued work, not needs-attention
    Given the store has a step in the inbox lane, a dependency-held step, an active step, and a queued step
    When I launch the dashboard
    Then the dependency-held step appears in the queued group, not the needs-attention group
    And the dependency-held step's icon is the queued glyph, not the needs-attention glyph

  Scenario: A needs-attention row shows its current step name
    Given the store has a step in the inbox lane at step "code-await-merge"
    When I launch the dashboard
    Then the needs-attention row for that step shows "code-await-merge" as its step

  Scenario: A needs-attention row shows its declared display phrase in place of its raw stage name
    Given the store has a step in the inbox lane at step "code-await-merge", with the display phrase "Review the PR" declared for that stage
    When I launch the dashboard
    Then the needs-attention row for that step shows "Review the PR" as its step

  Scenario: A gate renders an amber circle and an escalation a red triangle, with escalations sorted first
    Given the store has a gate step and an escalation step, both in the inbox lane
    When I launch the dashboard
    Then the gate's row shows icon "●" at colour amber
    And the escalation's row shows icon "▲" at colour red
    And the escalation's step-column text reads "stuck · build"
    And the escalation's row is positioned before the gate's row within the needs-attention group

  Scenario: An escalation row's "stuck ·" prefix carries the declared display phrase, not the raw stage name
    Given the store has a gate step and an escalation step, both in the inbox lane, with the display phrase "Coding" declared for the escalation step's stage
    When I launch the dashboard
    Then the escalation's step-column text reads "stuck · Coding"

  Scenario: A three-group list renders exactly one row per real item, at the spaced height, with no separator row
    Given the store has a step in the inbox lane, an active step, and a queued step
    When I launch the dashboard
    Then the table contains exactly 3 rows, one for each step, with no extra row of any kind
    And each row's key is a real node id
    And each row's rendered height is 2, one line of content plus one spacer line

  Scenario: An empty middle group contributes no rows and no extra gap between the groups either side of it
    Given the store has a step in the inbox lane and a queued step, with no active step
    When I launch the dashboard
    Then the active group renders no rows

  Scenario: A single non-empty group renders exactly its own rows and nothing else
    Given the store has only a queued step
    When I launch the dashboard
    Then the table contains exactly one row, for that queued step, with no extra row of any kind

  Scenario: Active items are grouped below needs-attention and above queued, with their own icon and colour
    Given the store has a step in the inbox lane, an active step, and a queued step
    When I launch the dashboard
    Then the active step's row is grouped below the needs-attention group and above the queued group
    And the active step's row is shown with its own icon and colour, distinct from the needs-attention and queued rows

  Scenario: The priority list includes an in-progress step in the active group
    Given the store has queued steps, blocked steps, and an in-progress step
    When I launch the dashboard
    Then the priority list contains a row for the in-progress step, in the active group

  Scenario: An active row shows its current step name alongside an approximate elapsed time
    Given the store has a step at step "build" that was claimed 14 minutes ago and is still in progress
    When I launch the dashboard
    Then the active row for that step shows "build" as its step
    And the active row's elapsed time reads "14m"

  Scenario: An active row shows its declared display phrase in place of its raw stage name
    Given the store has a step at step "build" that was claimed 14 minutes ago and is still in progress, with the display phrase "Coding" declared for that stage
    When I launch the dashboard
    Then the active row for that step shows "Coding" as its step

  Scenario: An active item's elapsed time updates as time passes, without disturbing the rest of the list
    Given the dashboard has launched with a step that was claimed some time ago and is still in progress
    When one poll interval elapses
    Then the active row's elapsed time reflects the additional time that passed
    And the priority list's rows stay in the same order

  Scenario: Queued items are grouped below active, with their own icon and colour
    Given the store has an active step and a queued step
    When I launch the dashboard
    Then the queued step's row is grouped below the active group
    And the queued step's row is shown with its own icon and colour, distinct from the active rows

  Scenario: A queued row shows its next step name
    Given the store has a queued step at step "build"
    When I launch the dashboard
    Then the queued row for that step shows "build" as its next step

  Scenario: A queued row shows its declared display phrase in place of its raw stage name
    Given the store has a queued step at step "build", with the display phrase "Coding" declared for that stage
    When I launch the dashboard
    Then the queued row for that step shows "Coding" as its next step

  Scenario: An item with an active step and a queued step of its own renders exactly one row, in the active group
    Given the store has an item with an active step and a queued step of its own
    When I launch the dashboard
    Then that item's row appears exactly once, in the active group
    And that item's row shows the item's own id and title, not the step's
    And the active row for that item shows its active step's own step name and elapsed time
    And that item's row's rendered height includes exactly one spacer line, the same as any other row

  Scenario: An item with a step in the inbox lane and a separate active step of its own appears only in the needs-attention group
    Given the store has an item with a step in the inbox lane and a separate active step of its own
    When I launch the dashboard
    Then that item's row appears exactly once, in the needs-attention group
    And that item's row does not also appear in the active group

  Scenario: A claimed queued item moves into the active group
    Given the dashboard has launched with a queued step
    When that step is claimed and becomes active
    And one poll interval elapses
    Then the step's row moves from the queued group into the active group

  Scenario Outline: A row whose title is too long to fit wraps instead of being truncated
    Given the store has a <group> step with a title longer than the priority list can fit on one line
    When I launch the dashboard
    Then that step's row wraps its title onto a second line rather than truncating it with an ellipsis
    And that step's row renders at a height of 3, two wrapped content lines plus one spacer line

    Examples:
      | group           |
      | needs-attention |
      | active          |
      | queued          |

  Scenario Outline: The id column widens to fit the longest id in the list, whatever produced it, without truncating or wrapping it
    Given the store has a queued step with id "<id>" (<id source>)
    When I launch the dashboard
    Then that step's row shows "<id>" as its id, in full, on one line

    Examples:
      | id source                                    | id                |
      | this project's own shortcode                 | LC-143.3.6        |
      | a plain generated id                         | fake-56f47088     |
      | the engine's default, unshortened shortcode  | LIGHTCYCLE-3.1.1  |

  Scenario: The id column's width already accounts for an id further down the list than the visible rows
    Given the store has more queued steps than fit on one screen, one of which has a longer id than any visible row
    When I launch the dashboard
    Then the id column is already wide enough for that off-screen id, before it is scrolled into view

  Scenario Outline: When a row cannot fit unstacked, the title moves to a continuation line indented by the grid's glyph width and spanning the row without wrapping mid-word
    Given a row whose atomic and glyph columns leave less than the flexible minimum for the title, on a terminal <at a width>
    When I launch the dashboard
    Then the cursor, icon, id, project and step remain on the row's first line, each padded to its atomic width, with time right-aligned alongside them
    And the title appears on a continuation line indented 6 characters - the row's glyph width, not where the title column starts in the unstacked grid
    And no fragment of the title's prose is split mid-word
    And that row renders at a height of 3, the row's first line plus one continuation line plus one spacer line

    Examples:
      | at a width                            |
      | just narrow enough to force stacking  |
      | just wide enough to clear the floor   |

  Scenario: Every row shows the project it belongs to
    Given the store has a step in the blocked lane, an active step, and a queued step, each belonging to the registered project "lightcycle"
    When I launch the dashboard
    Then every row shows "lightcycle" as its project

  Scenario: A step with no registered project shows a blank project field
    Given the store has a queued step with no registered project
    When I launch the dashboard
    Then that step's row shows a blank project field

  Scenario: The terminal bell rings the moment a step enters needs-attention
    Given the dashboard has launched with no needs-attention steps
    When a step is created directly into the inbox lane
    And one poll interval elapses
    Then the terminal bell has rung once

  Scenario: The terminal bell does not ring when a step becomes dependency-blocked
    Given the dashboard has launched with no needs-attention steps
    When a step becomes blocked by an unresolved dependency
    And one poll interval elapses
    Then the terminal bell has not rung

  Scenario: The terminal bell does not ring again while a step remains in needs-attention
    Given the dashboard has launched and a step has already entered needs-attention, ringing the bell once
    When one more poll interval elapses with nothing new entering needs-attention
    Then the terminal bell has not rung again

  Scenario: The terminal bell does not ring for a step entering active or queued
    Given the dashboard has launched with no needs-attention steps
    When a new step is created directly into the queue
    And one poll interval elapses
    Then the terminal bell has not rung

  Scenario: The terminal bell does not ring for a needs-attention item already present at launch
    Given the store has a step already in the inbox lane
    When I launch the dashboard
    Then the terminal bell has not rung

  Scenario: Down moves the selection to the next row
    Given the store has three queued steps
    When I launch the dashboard
    And Down is pressed
    Then the selection has moved to the second row

  Scenario: Up does not wrap the selection past the first row
    Given the store has three queued steps
    When I launch the dashboard
    And Up is pressed
    Then the selection has not moved from the first row

  Scenario: Down does not wrap the selection past the last row
    Given the store has three queued steps
    When I launch the dashboard
    And the selection is on the last row
    And Down is pressed
    Then the selection has not moved past the last row

  Scenario: Down visits every row's id exactly once, in order, and holds on the last row
    Given the store has a step in the inbox lane, an active step, and a queued step
    When I launch the dashboard
    And Down is pressed 3 times
    Then the selection has visited the needs-attention row, then the active row, then the queued row, each exactly once
    When Down is pressed once more
    Then the selection is still on the queued row

  Scenario: A selected row's highlight covers every line of that row, spacer included
    Given the store has three queued steps
    When I launch the dashboard
    Then every line of the selected row's rendered height carries the same cursor-highlight background colour
    And that colour differs from an unselected row's background colour

  Scenario: Ctrl-D jumps the selection forward by the same amount as Page Down
    Given the store has more queued steps than fit on one screen
    When I launch the dashboard
    And Ctrl-D is pressed
    Then the selection has moved forward by the same amount Page Down would move it

  Scenario: Ctrl-U jumps the selection back by the same amount as Page Up
    Given the store has more queued steps than fit on one screen
    When I launch the dashboard
    And Ctrl-D is pressed
    And Ctrl-U is pressed
    Then the selection is back on the row it started on

  Scenario: The selection follows a selected step that moves group between polls
    Given the dashboard has launched with a selected queued step
    When that step is claimed and becomes active
    And one poll interval elapses
    Then the selection is still on that step, now in the active group

  Scenario: The selection falls to a nearby remaining row when the selected step leaves the list
    Given the dashboard has launched with a selected step
    When that step is completed
    And one poll interval elapses
    Then the selection is on a remaining row near the previous position

  Scenario: A queued row that is dependency-held shows the dependency chain-link icon and the blocking item's id
    Given the store has a step blocked on another item's completion
    When I launch the dashboard
    Then that step's row shows the dependency chain-link icon alongside its queued icon
    And that step's row shows the blocking item's id in its step cell

  Scenario: A dependency-held row keeps showing the blocking item's id even when its own stage has a declared display phrase
    Given the store has a step blocked on another item's completion, with the display phrase "Coding" declared for that step's own stage
    When I launch the dashboard
    Then that step's row shows the blocking item's id in its step cell, not "Coding"

  Scenario: A needs-attention row sourced from the inbox lane shows no dependency indicator
    Given the store has a step in the inbox lane
    When I launch the dashboard
    Then that step's row shows no dependency chain-link icon

  Scenario: Within the queued group, runnable work is positioned before dependency-held work
    Given the store has a runnable queued step and a dependency-held queued step
    When I launch the dashboard
    Then the runnable step's row is positioned before the dependency-held step's row

  Scenario: A calm message replaces the priority list when nothing needs attention, is active, or is queued
    Given the store has no steps in any lane
    When I launch the dashboard
    Then a calm message is shown in place of the priority list

  Scenario: The calm message is replaced by the priority list once work appears
    Given the dashboard has launched with no steps in any lane
    When a new step is created into the queue
    And one poll interval elapses
    Then the priority list is shown in place of the calm message
    And the new step's row is built at the table's real width, not a stranded single-character wrap
