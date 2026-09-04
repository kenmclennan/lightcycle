Feature: Breaker recovers when its probe worker stalls
  While the breaker is open and past its reset time, it allows exactly one
  probe worker to test whether capacity has returned. If that probe stalls
  instead of finishing, a stall is inconclusive - it is never treated as a
  successful probe, because a stall says nothing about whether Claude is
  available. A probe worker that dies outright, having produced no session
  activity at all, is inconclusive for the same reason and is likewise never
  treated as a successful probe. The breaker's own reset time is re-armed forward by a
  configured probe cooldown instead, so a fresh probe becomes eligible
  later rather than the breaker being left with a stale reset time and no
  path back to recovery.

  Background:
    Given a breaker gate use case backed by a breaker port, a workers port, and an fs port

  Scenario: A stalled probe is not treated as a successful probe
    Given the breaker is open and past its reset time
    And the probe worker is alive and its log has stalled
    When the pool's breaker gate runs
    Then the breaker does not close
    And the breaker does not treat the stall as a successful probe

  Scenario: A stalled probe re-arms the reset time by the probe cooldown
    Given the breaker is open and past its reset time
    And the probe worker is alive and its log has stalled
    When the pool's breaker gate runs
    Then the breaker stays open
    And the reset time is re-armed to now plus the probe cooldown

  Scenario: A probe log that has not yet crossed the stall threshold is left alone
    Given the breaker is open and past its reset time
    And the probe worker is alive and its log grew within the stall threshold
    When the pool's breaker gate runs
    Then the reset time is not re-armed
    And the reset time is unchanged from the state that was loaded

  Scenario: A stalled worker that already committed to exiting is not treated as a stalled probe
    Given the breaker is open and past its reset time
    And the probe worker is alive and its log has stalled
    And the probe worker's log shows a terminal marker
    When the pool's breaker gate runs
    Then the reset time is not re-armed

  Scenario Outline: Re-arming only happens while the breaker is actually probing
    Given the breaker's state is <breaker_state>
    And an alive worker's log has stalled
    When the pool's breaker gate runs
    Then the reset time is <rearm_verdict>

    Examples:
      | breaker_state                        | rearm_verdict |
      | closed                                | not re-armed |
      | open but not yet past its reset time  | not re-armed |
      | open and past its reset time          | re-armed     |

  Scenario: A concurrent rejection takes precedence over a stalled probe
    Given the breaker is open and past its reset time
    And a different worker is dead, unchecked, and its log carries a rate-limit rejection
    And the probe worker is alive and its log has stalled
    When the pool's breaker gate runs
    Then the breaker opens with the rejection's reset time
    And the reset time is not re-armed

  Scenario: A probe that completes normally still closes the breaker
    Given the breaker is open and past its reset time
    And the probe worker is dead, unchecked, and its log carries no rejection
    When the pool's breaker gate runs
    Then the breaker closes

  Scenario: A probe that dies having done no work is not treated as a successful probe either
    Given the breaker is open and past its reset time
    And the probe worker is dead, unchecked, and its log carries neither a rejection nor any session activity
    When the pool's breaker gate runs
    Then the breaker does not close

  Scenario: A probe that completes with a rejection still re-trips the breaker
    Given the breaker is open and past its reset time
    And the probe worker is dead, unchecked, and its log carries a rate-limit rejection
    When the pool's breaker gate runs
    Then the breaker opens with the rejection's reset time

  Scenario: Recovery is re-entrant once the re-armed reset time has passed
    Given the breaker's reset time was re-armed by a probe cooldown
    And no worker is alive
    When the re-armed reset time has passed
    Then the breaker allows a fresh probe to spawn
