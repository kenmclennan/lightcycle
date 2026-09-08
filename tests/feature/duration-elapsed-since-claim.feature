Feature: Elapsed time since claim, for a still-running step
  A step's claim moment is durably recorded as its first RUNNING history
  transition. Duration.elapsed_since_claim(now) turns that transition, plus
  an explicit "now" the caller supplies, into how long a still-active step
  has been running - the one figure elapsed() cannot produce, since it
  requires a DONE transition that a running step does not have yet.

  Background:
    Given a duration computed from a step's history transitions

  Scenario: An active step's elapsed time is measured from its claim to now
    Given the history has a RUNNING transition at "2026-01-01T10:00:00" and no DONE transition
    When elapsed_since_claim is computed with now "2026-01-01T10:30:00"
    Then the elapsed duration is 30 minutes

  Scenario: A step that has not yet been claimed has no elapsed time
    Given the history has only a WAITING transition and no RUNNING transition
    When elapsed_since_claim is computed with now "2026-01-01T10:30:00"
    Then the elapsed duration is unknown

  Scenario: A finished step has no elapsed-since-claim, even measured against a later now
    Given the history has a RUNNING transition at "2026-01-01T10:00:00" and a DONE transition at "2026-01-01T10:30:00"
    When elapsed_since_claim is computed with now "2026-01-01T12:00:00"
    Then the elapsed duration is unknown

  Scenario: A reworked step still active is measured from its first claim, not its most recent one
    Given the history has a RUNNING transition at "2026-01-01T10:00:00", then a WAITING transition, then a second RUNNING transition at "2026-01-01T11:00:00", and no DONE transition
    When elapsed_since_claim is computed with now "2026-01-01T11:30:00"
    Then the elapsed duration is 1 hour 30 minutes

  Scenario: A claim transition with a missing timestamp yields no elapsed time
    Given the history has a RUNNING transition with no timestamp and no DONE transition
    When elapsed_since_claim is computed with now "2026-01-01T10:30:00"
    Then the elapsed duration is unknown

  Scenario: elapsed() keeps measuring claim-to-done unchanged alongside the new computation
    Given the history has a RUNNING transition at "2026-01-01T10:00:00" and a DONE transition at "2026-01-01T10:30:00"
    When elapsed is computed
    Then the elapsed duration is 30 minutes
