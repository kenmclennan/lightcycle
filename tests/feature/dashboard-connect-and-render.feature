Feature: The dashboard connects to the store and renders on launch
  Launching the dashboard connects it to the lightcycle store and renders a
  priority list of ready and blocked work, with a status bar showing the
  pool's running state, the breaker's state, the installed version, and
  whether a newer version is available, all visible in the very first
  rendered frame rather than as a separate loading step. The dashboard then
  stays live, polling the store on a fixed interval so the list and status
  bar reflect changes without a restart.

  Scenario: Launching the dashboard renders the priority list
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then the priority list is rendered with one row per queued or blocked step

  Scenario: The status bar appears in the same initial frame as the priority list
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then the priority list and the status bar are both visible in the first rendered frame

  Scenario: The priority list is not truncated to the first ten steps
    Given the store has more than ten queued or blocked steps
    When I launch the dashboard
    Then the priority list contains a row for every one of them

  Scenario Outline: The status bar reports the pool's running state
    Given the pool is <state>
    When I launch the dashboard
    Then the status bar reports the pool as <state>

    Examples:
      | state       |
      | running     |
      | not running |

  Scenario: The status bar reports a closed breaker
    Given the breaker is closed
    When I launch the dashboard
    Then the status bar reports the breaker as closed

  Scenario: The status bar reports an open breaker with its reset time
    Given the breaker is open with a reset time
    When I launch the dashboard
    Then the status bar reports the breaker as open with that reset time

  Scenario: The status bar always shows the installed version
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then the status bar shows the installed version

  Scenario: The status bar shows the upgrade indicator when a newer version is available
    Given a newer version is available
    When I launch the dashboard
    Then the status bar shows the upgrade indicator with that version

  Scenario: The status bar shows no upgrade indicator when the installed version is current
    Given no newer version is available
    When I launch the dashboard
    Then the status bar shows no upgrade indicator

  Scenario: The status bar shows no upgrade indicator when the upgrade check fails
    Given the upgrade check fails
    When I launch the dashboard
    Then the status bar shows no upgrade indicator
    And the priority list is rendered with one row per queued or blocked step

  Scenario: The dashboard's poll interval is ten seconds
    Given the dashboard has launched
    When the dashboard's poll interval is read
    Then it is ten seconds

  Scenario: The priority list stays live by polling on the fixed interval
    Given the dashboard has launched and rendered the initial priority list
    When the store's queue changes
    And one poll interval elapses
    Then the priority list reflects the changed queue

  Scenario: The status bar stays live by polling on the fixed interval
    Given the dashboard has launched and rendered the initial status bar
    When the pool or breaker state changes
    And one poll interval elapses
    Then the status bar reflects the changed state
