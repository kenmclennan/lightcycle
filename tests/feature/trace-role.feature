@wip
Feature: The trace read path exposes each step's role
  The Hierarchy tab and Node Hub render a step's role (write-code, review-code, human, ...)
  from the same read path that already returns its id, state, and log. This is the
  behavioural spec for that read path, independent of any implementation language.

  Background:
    Given a flow where the coder builds, the reviewer reviews, and the pr-watcher opens the PR
    And the item "specs/login.md" is filed at step "open-pr"

  Scenario: An agent-owned step's role appears in the trace
    When I trace the item
    Then the open-pr step's role in the trace is "pr-watcher"

  Scenario: A human-owned step's role appears in the trace unchanged
    Given the pr-watcher has claimed and completed the open-pr step with outcome "done"
    When I trace the item
    Then the ready-merge step's role in the trace is "human"

  Scenario: The trace still carries a step's id, state, and log alongside its role
    When I trace the item
    Then the open-pr step in the trace has its id, state, and log
