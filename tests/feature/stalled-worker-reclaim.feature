Feature: Pool detects and reclaims a stalled worker
  A worker that is alive but making no progress is, to the pool, indistinguishable
  from a healthy long-running one unless the pool checks for progress directly.
  Progress is measured by growth of the worker's own log, not by wall-clock
  runtime, so a legitimately long-running step is never killed for being long,
  and a worker frozen through a suspend/resume is still caught on the next sweep.

  @wip
  Scenario Outline: Whether a claimed worker is treated as stalled depends on log growth and a terminal marker
    Given a worker has claimed a step
    And the worker is past its boot window
    And the worker's log last grew <log_growth>
    And the worker's log <terminal_state>
    When the pool sweeps
    Then the worker is <verdict> as stalled

    Examples:
      | log_growth                        | terminal_state                | verdict        |
      | more than the stall threshold ago | contains no terminal marker   | identified     |
      | within the stall threshold        | contains no terminal marker   | not identified |
      | more than the stall threshold ago | contains a terminal marker    | not identified |

  @wip
  Scenario: A worker still inside its boot window is governed by the boot window, not the stall check
    Given a worker has not yet claimed a step
    And the worker is still inside its boot window
    And the worker's log last grew more than the stall threshold ago
    When the pool sweeps
    Then the worker is not identified as stalled

  @wip
  Scenario: A stalled worker is killed, its record marked checked, and its step reclaimed to ready
    Given a worker has claimed a step
    And the worker's log last grew more than the stall threshold ago
    And the worker's log contains no terminal marker
    And the worker is past its boot window
    When the pool sweeps
    Then the worker is killed
    And the worker's record is marked checked
    And the step is reclaimed to ready

  @wip
  Scenario: A worker frozen through a long suspend is stalled on resume, not freshly started
    Given a worker has claimed a step
    And the worker's log stopped growing well before a multi-hour suspend
    And the wall clock then advances by several hours across the suspend
    When the pool sweeps after the resume
    Then the worker is identified as stalled
    And the worker is not treated as though it just started

  @wip
  Scenario: A stalled worker's uncommitted work is preserved on reclaim, the same as any other reclaimed step
    Given a worker has claimed a step
    And the worker's log last grew more than the stall threshold ago
    And the worker's log contains no terminal marker
    And the worker is past its boot window
    And the step's worktree has uncommitted changes
    When the pool sweeps
    Then the uncommitted changes are committed before the step is reclaimed to ready
