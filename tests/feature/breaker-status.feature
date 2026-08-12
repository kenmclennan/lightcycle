Feature: Breaker state can be read on demand without side effects
  The pool's circuit breaker tracks whether it is open and, if so, when it
  resets. Today that state is only visible as transient tick log lines. This
  is the behavioural spec for a read-only query that returns the state at
  rest, on demand, independent of any implementation language.

  Background:
    Given a breaker status use case backed by a breaker port

  @wip
  Scenario: Reading a closed breaker's status
    Given the breaker's persisted state is closed
    When the breaker status is read
    Then the status is closed

  @wip
  Scenario: Reading an open breaker's status
    Given the breaker's persisted state is open with a reset time
    When the breaker status is read
    Then the status is open with that reset time

  @wip
  Scenario: The status reflects the latest persisted state, not a cached snapshot
    Given the breaker's persisted state is closed
    And the breaker status has already been read once
    When the breaker's persisted state changes to open with a reset time
    And the breaker status is read again
    Then the status is open with that reset time

  @wip
  Scenario: Reading the breaker status never writes back to the port
    Given the breaker's persisted state is closed
    When the breaker status is read
    Then the breaker port was never saved to

  @wip
  Scenario: A breaker with no persisted state yet reads as closed
    Given the breaker has no persisted state
    When the breaker status is read
    Then the status is closed
