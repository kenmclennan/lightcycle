Feature: A step whose worker keeps dying without doing any work is capped and handed to a human
  A worker that dies before producing any model output leaves no evidence either way about
  whether the step is workable - only that this particular attempt produced nothing. The pool
  retries automatically, the same as any other reclaim, but a step whose worker dies this way
  over and over is not being retried into progress; it is spinning. Once a step has died with no
  work a configured number of times in a row, the pool stops retrying it silently and hands it to
  a human instead, carrying what actually happened. Real session activity - or a death for which
  no worker record exists at all - is not part of this pattern and does not count toward it.

  Background:
    Given the spin cap is 3

  @wip
  Scenario Outline: What counts as a worker having done real work
    Given a worker's log has <log_contents>
    Then the log is judged to show session activity: <activity_found>

    Examples:
      | log_contents                         | activity_found |
      | an assistant event                   | yes            |
      | a result event                       | yes            |
      | only a rate-limit rejection event     | no             |
      | no lines at all                      | no             |
      | only plain, non-JSON diagnostic text | no             |

  @wip
  Scenario Outline: Whether a step whose worker died is reclaimed or parked depends on the no-work streak reaching the spin cap
    Given a worker has claimed a step
    And the worker died having <activity>
    And the step has previously died this way <prior_count> times in a row
    When the pool sweeps
    Then the step is <verdict>

    Examples:
      | activity                    | prior_count | verdict            |
      | done no work                | 0           | reclaimed to ready |
      | done no work                | 1           | reclaimed to ready |
      | done no work                | 2           | parked for a human |
      | shown real session activity | 2           | reclaimed to ready |

  @wip
  Scenario: Real session activity resets a step's no-work streak to zero
    Given a worker has claimed a step
    And the step has previously died having done no work 2 times in a row
    And the worker died having shown real session activity
    When the pool sweeps
    Then the step is reclaimed to ready
    And the step's no-work streak is reset to zero

  @wip
  Scenario: A step with no dead-worker record on file is reclaimed normally
    Given a worker has claimed a step
    And no dead worker is on record for the step
    When the pool sweeps
    Then the step is reclaimed to ready
    And the step's no-work streak is unaffected

  @wip
  Scenario: A stalled (alive) worker being killed does not affect the no-work streak
    Given a worker has claimed a step
    And the worker's log last grew more than the stall threshold ago
    And the worker's log contains no terminal marker
    And the worker is past its boot window
    When the pool sweeps
    Then the worker is killed
    And the step is reclaimed to ready
    And the step's no-work streak is unaffected

  @wip
  Scenario: The park that caps a spinning step records what actually happened
    Given a worker has claimed a step
    And the step has previously died having done no work 2 times in a row
    And the worker died having done no work, its log ending with "Failed to authenticate: OAuth session expired and could not be refreshed"
    When the pool sweeps
    Then the step is parked for a human, not reclaimed
    And the step's role is human
    And the park's observation states the step died 3 times in a row with no observed work
    And the park's observation states the elapsed span since the first death in the streak
    And the park's observation states the last line of the most recent worker's log
    And the step's notes carry a BLOCKED note

  @wip
  Scenario: Unblocking a parked step starts its no-work streak over
    Given a step was parked after its worker died 3 times in a row with no work
    When I unblock the step
    And the step's worker later dies again having done no work
    Then the step is reclaimed to ready, not parked
