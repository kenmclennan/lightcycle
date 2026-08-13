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

  Scenario: Needs-attention groups inbox and blocked steps together, not interleaved with active or queued
    Given the store has a step in the inbox lane, a step in the blocked lane, an active step, and a queued step
    When I launch the dashboard
    Then the inbox step and the blocked step both appear together in the needs-attention group, above the active and queued groups
    And neither of them appears in the active group or the queued group

  Scenario: A needs-attention row shows its current step name
    Given the store has a step in the blocked lane at step "code-await-merge"
    When I launch the dashboard
    Then the needs-attention row for that step shows "code-await-merge" as its step

  Scenario: A single blank row separates two adjacent non-empty groups
    Given the store has a step in the inbox lane, an active step, and a queued step
    When I launch the dashboard
    Then there is exactly one blank separator row between the needs-attention group and the active group
    And there is exactly one blank separator row between the active group and the queued group

  Scenario: An empty middle group contributes no rows and no extra gap between the groups either side of it
    Given the store has a step in the inbox lane and a queued step, with no active step
    When I launch the dashboard
    Then the active group renders no rows
    And there is exactly one blank separator row between the needs-attention group and the queued group

  Scenario: A single group with nothing above or below it has no separator row
    Given the store has only a queued step
    When I launch the dashboard
    Then the priority list has no blank separator row

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

  Scenario: A claimed queued item moves into the active group
    Given the dashboard has launched with a queued step
    When that step is claimed and becomes active
    And one poll interval elapses
    Then the step's row moves from the queued group into the active group

  Scenario Outline: A row whose title is too long to fit wraps instead of being truncated
    Given the store has a <group> step with a title longer than the priority list can fit on one line
    When I launch the dashboard
    Then that step's row wraps its title onto a second line rather than truncating it with an ellipsis

    Examples:
      | group           |
      | needs-attention |
      | active          |
      | queued          |

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
    When a step becomes blocked by an unresolved dependency
    And one poll interval elapses
    Then the terminal bell has rung once

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
    Given the store has a step already in the blocked lane
    When I launch the dashboard
    Then the terminal bell has not rung
