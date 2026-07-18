Feature: The PR-feedback cycle spawns and settles handle-feedback steps
  An outstanding @lc mention or unresolved review comment on a watched PR opens a
  handle-feedback step exactly once - not once per tick, and not a second time just because
  the first attempt closed without clearing the feedback.

  Background:
    Given a flow where "await-merge" reacts to "@lc" PR feedback with "handle-feedback"
    And the item "specs/x.md" is awaiting merge with PR "https://github.com/x/y/pull/1"
    And the PR has an outstanding "@lc" mention

  Scenario: Outstanding feedback opens exactly one handle-feedback step across ticks
    When the pool ticks
    Then there is one ready step for "handle-feedback"
    When the handle-feedback step is marked done without clearing the feedback
    And the pool ticks again
    Then there is still exactly one handle-feedback step in total

  Scenario: Advancing the watermark stops the same mention from re-triggering
    When the pool ticks
    Then there is one ready step for "handle-feedback"
    When the handle-feedback step replies and advances the watermark
    And the pool ticks again
    Then there are no ready steps for "handle-feedback"
