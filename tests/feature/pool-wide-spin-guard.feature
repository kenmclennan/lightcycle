Feature: The pool caps itself to one worker when many workers die at once with no work
  A single step dying with no work repeatedly is capped per-step. But when several workers,
  each holding a different step, all die within the same check having produced no work and
  without a rate-limit rejection, that is evidence of an engine-level problem rather than a
  step-level one - an auth failure kills every worker the same way, not just one step's. When
  at least two such deaths land together, the pool caps itself to a single concurrent worker
  until a later check observes real activity, and hands one representative step to a human
  describing the pattern as pool-wide. A worker that died before ever being assigned a step
  never counts toward this - that is an idle race, not a broken engine.

  Background:
    Given a breaker gate use case backed by a breaker port, a workers port, an fs port, a spin port, and a store
    And the spin cap is 1

  @wip
  Scenario: At least two workers with an assigned step dying together with no work and no rejection trips the pool-wide guard
    Given 2 dead, unchecked workers, each with an assigned step, each having done no work
    And none of them carries a rate-limit rejection
    When the pool's breaker gate runs
    Then the pool-wide spin guard opens
    And a step is parked for a human, its observation naming the pattern as pool-wide, not step-specific

  @wip
  Scenario: A single dead worker with no work does not trip the pool-wide guard
    Given 1 dead, unchecked worker, with an assigned step, having done no work
    And it carries no rate-limit rejection
    When the pool's breaker gate runs
    Then the pool-wide spin guard stays closed

  @wip
  Scenario: A rate-limit rejection takes precedence over the pool-wide no-work tally
    Given 2 dead, unchecked workers, each with an assigned step, each having done no work
    And one of them carries a rate-limit rejection
    When the pool's breaker gate runs
    Then the pool-wide spin guard stays closed

  @wip
  Scenario: A dead worker with no assigned step never counts toward the pool-wide tally
    Given 1 dead, unchecked worker with no assigned step, having done no work
    And no other dead, unchecked workers this check
    When the pool's breaker gate runs
    Then the pool-wide spin guard stays closed

  @wip
  Scenario: Real activity among the dead workers resets an advancing pool-wide streak
    Given the spin cap is 3
    And the pool-wide spin guard's streak has already advanced from an earlier check
    And 2 dead, unchecked workers, each with an assigned step, this check
    And one of them shows real session activity
    When the pool's breaker gate runs
    Then the pool-wide spin guard's streak resets
    And the pool-wide spin guard stays closed

  @wip
  Scenario: The pool-wide streak accumulates one check at a time and only trips once it reaches a cap above 1
    Given the spin cap is 3
    And 2 dead, unchecked workers, each with an assigned step, each having done no work, this check
    And none of them carries a rate-limit rejection
    When the pool's breaker gate runs
    Then the pool-wide spin guard stays closed
    Given 2 dead, unchecked workers, each with an assigned step, each having done no work, this check
    And none of them carries a rate-limit rejection
    When the pool's breaker gate runs
    Then the pool-wide spin guard stays closed
    Given 2 dead, unchecked workers, each with an assigned step, each having done no work, this check
    And none of them carries a rate-limit rejection
    When the pool's breaker gate runs
    Then the pool-wide spin guard opens

  @wip
  Scenario: The pool-wide spin guard clears automatically the moment real activity is observed, with no cooldown
    Given the pool-wide spin guard is open
    When a later check observes real session activity among the dead-with-step workers
    Then the pool-wide spin guard closes on that same check

  @wip
  Scenario: While the pool-wide spin guard is open, the pool caps itself to one concurrent worker
    Given the pool-wide spin guard is open
    And the pool has more than one free slot
    When the pool ticks
    Then no more than 1 worker is spawned
