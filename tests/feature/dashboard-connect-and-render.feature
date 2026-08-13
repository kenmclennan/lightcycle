Feature: The dashboard connects to the store and renders on launch
  Launching the dashboard connects it to the lightcycle store and renders a
  priority list of ready and blocked work, with a status bar showing the
  pool's running state and the breaker's state, both visible in the very
  first rendered frame rather than as a separate loading step. The dashboard
  then stays live, polling the store on a fixed interval so the list and
  status bar reflect changes without a restart.

  @wip
  Scenario: Launching the dashboard renders the priority list
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then the priority list is rendered with one row per queued or blocked step

  @wip
  Scenario: The status bar appears in the same initial frame as the priority list
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then the priority list and the status bar are both visible in the first rendered frame

  @wip
  Scenario: The priority list includes queued and blocked steps but not in-progress steps
    Given the store has queued steps, blocked steps, and an in-progress step
    When I launch the dashboard
    Then the priority list contains one row for each queued and blocked step
    And the priority list does not contain a row for the in-progress step

  @wip
  Scenario: The priority list is not truncated to the first ten steps
    Given the store has more than ten queued or blocked steps
    When I launch the dashboard
    Then the priority list contains a row for every one of them

  @wip
  Scenario Outline: The status bar reports the pool's running state
    Given the pool is <state>
    When I launch the dashboard
    Then the status bar reports the pool as <state>

    Examples:
      | state       |
      | running     |
      | not running |

  @wip
  Scenario: The status bar reports a closed breaker
    Given the breaker is closed
    When I launch the dashboard
    Then the status bar reports the breaker as closed

  @wip
  Scenario: The status bar reports an open breaker with its reset time
    Given the breaker is open with a reset time
    When I launch the dashboard
    Then the status bar reports the breaker as open with that reset time

  @wip
  Scenario: The dashboard's poll interval is ten seconds
    Given the dashboard has launched
    When the dashboard's poll interval is read
    Then it is ten seconds

  @wip
  Scenario: The priority list stays live by polling on the fixed interval
    Given the dashboard has launched and rendered the initial priority list
    When the store's queue changes
    And one poll interval elapses
    Then the priority list reflects the changed queue

  @wip
  Scenario: The status bar stays live by polling on the fixed interval
    Given the dashboard has launched and rendered the initial status bar
    When the pool or breaker state changes
    And one poll interval elapses
    Then the status bar reflects the changed state
