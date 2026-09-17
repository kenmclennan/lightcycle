Feature: The stats screen

  The stats tab is the fourth top-level screen, reached from the done tab by
  Tab or the tab strip (priority list -> backlog -> done -> stats -> priority
  list). It shows seven store-wide rows for one day, as a table: items
  completed, items closed, cost, escalations, audits, backlog size and
  backlog delta - defaulting to today. It has its own independent day picker,
  shared with the done tab's own. Pressing Enter opens the done tab filtered
  to whichever day stats is currently showing, for the per-item breakdown.

  Scenario: The stats tab is reachable via Tab alongside the other three
    Given the store has no closed items anywhere
    When I switch to the stats tab
    Then the stats tab is shown

  Scenario: The stats tab shows seven rows for today by default
    Given the store has a closed item today, costing money, with a completed disposition
    When I switch to the stats tab
    Then the stats table shows 1 items completed and 1 items closed
    And the stats table shows a recorded cost

  Scenario: Pressing d opens a day picker listing today, even at zero, and every day that closed something
    Given the store has closed items on two distinct days before today
    When I switch to the stats tab
    And d is pressed
    Then the picker's header reads "Filter by day"
    And the picker shows today with a zero count
    And the picker shows each distinct day with its own item count, most recent first

  Scenario: Selecting a day updates the table and the day filter bar
    Given the store has closed items on two distinct days before today
    When I switch to the stats tab
    And d is pressed
    And Down is pressed
    And Down is pressed
    And Enter is pressed
    Then the stats day filter row shows the earlier day
    And the stats table shows 1 items completed and 1 items closed

  Scenario: Pressing Enter opens the done tab filtered to the day stats is showing
    Given the store has closed items on two distinct days before today
    When I switch to the stats tab
    And d is pressed
    And Down is pressed
    And Down is pressed
    And Enter is pressed
    And Enter is pressed
    Then the done tab is shown, filtered to the earlier day, with its row already populated
