Feature: The report screen

  The report tab is the fourth top-level screen, reached from the done tab by
  Tab or the tab strip (priority list -> backlog -> done -> report -> priority
  list). It shows one markdown document for one day, defaulting to today: a title
  with the day, then a top line with items closed, cost, automation items and
  their cost, escalations and the backlog from the day's starting midnight to
  the next one with its delta. On the current day the closing size is live and
  keeps moving. After the top line it shows one section per project that
  closed work that day, ordered by items closed then name, each with a one
  line summary of that project's own figures and its share of the summary's
  Delivered, Fixed and Improved lists as headed bullets with their item ids in
  parentheses; any summary line that cannot be placed stays in a final
  section headed Not matched to a project. It has its own independent day
  picker, shared with the done tab's own. Pressing Enter opens the done tab
  filtered to whichever day report is currently showing, for the per-item
  breakdown.

  Scenario: The report tab is reachable via Tab alongside the other three
    Given the store has no closed items anywhere
    When I switch to the report tab
    Then the report tab is shown

  Scenario: The report tab shows its document for today by default
    Given the store has a closed item today, costing money, with a completed disposition
    When I switch to the report tab
    Then the report document shows 1 item closed
    And the report document shows a recorded cost

  Scenario: Pressing d opens a day picker listing today, even at zero, and every day that closed something
    Given the store has closed items on two distinct days before today
    When I switch to the report tab
    And d is pressed
    Then the picker's header reads "Filter by day"
    And the picker shows today with a zero count
    And the picker shows each distinct day with its own item count, most recent first

  Scenario: Selecting a day updates the document and the day filter bar
    Given the store has closed items on two distinct days before today
    When I switch to the report tab
    And d is pressed
    And Down is pressed
    And Down is pressed
    And Enter is pressed
    Then the report day filter row shows the earlier day
    And the report document shows 1 item closed

  Scenario: Pressing Enter opens the done tab filtered to the day report is showing
    Given the store has closed items on two distinct days before today
    When I switch to the report tab
    And d is pressed
    And Down is pressed
    And Down is pressed
    And Enter is pressed
    And Enter is pressed
    Then the done tab is shown, filtered to the earlier day, with its row already populated

  Scenario: A day with a stored summary shows it in the document
    Given the store has a closed item today with a stored daily summary
    When I switch to the report tab
    Then the report document ends with the stored text under its own heading

  Scenario: A day with no stored summary shows no unmatched section
    Given the store has a closed item today, costing money, with a completed disposition
    When I switch to the report tab
    Then the report document has no unmatched section
