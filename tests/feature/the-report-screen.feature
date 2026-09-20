Feature: The report screen

  The report tab is the fourth top-level screen, reached from the done tab by
  Tab or the tab strip (priority list -> backlog -> done -> report -> priority
  list). It shows nine store-wide rows for one day, as a table: items
  completed, items closed, cost, automation items, automation cost, escalations, starting backlog
  size (as of that day's midnight), closing backlog size (as of the next
  midnight) and backlog delta (closing minus starting) - defaulting to
  today. On the current day the closing size is live and keeps moving. Below the table, it shows the day's
  stored prose summary when one has been generated, and no summary widget at
  all otherwise. It has its own independent day picker, shared with the done
  tab's own. Pressing Enter opens the done tab filtered to whichever day
  report is currently showing, for the per-item breakdown.

  Scenario: The report tab is reachable via Tab alongside the other three
    Given the store has no closed items anywhere
    When I switch to the report tab
    Then the report tab is shown

  Scenario: The report tab shows eight rows for today by default
    Given the store has a closed item today, costing money, with a completed disposition
    When I switch to the report tab
    Then the report table shows 1 items completed and 1 items closed
    And the report table shows a recorded cost

  Scenario: Pressing d opens a day picker listing today, even at zero, and every day that closed something
    Given the store has closed items on two distinct days before today
    When I switch to the report tab
    And d is pressed
    Then the picker's header reads "Filter by day"
    And the picker shows today with a zero count
    And the picker shows each distinct day with its own item count, most recent first

  Scenario: Selecting a day updates the table and the day filter bar
    Given the store has closed items on two distinct days before today
    When I switch to the report tab
    And d is pressed
    And Down is pressed
    And Down is pressed
    And Enter is pressed
    Then the report day filter row shows the earlier day
    And the report table shows 1 items completed and 1 items closed

  Scenario: Pressing Enter opens the done tab filtered to the day report is showing
    Given the store has closed items on two distinct days before today
    When I switch to the report tab
    And d is pressed
    And Down is pressed
    And Down is pressed
    And Enter is pressed
    And Enter is pressed
    Then the done tab is shown, filtered to the earlier day, with its row already populated

  Scenario: A day with a stored summary shows it below the table
    Given the store has a closed item today with a stored daily summary
    When I switch to the report tab
    Then the report summary is shown, reading the stored text
    And the report summary sits below the table

  Scenario: A day with no stored summary shows no summary widget at all
    Given the store has a closed item today, costing money, with a completed disposition
    When I switch to the report tab
    Then no report summary is shown
