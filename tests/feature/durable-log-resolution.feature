Feature: A step's log is found even after its worker registry entry is pruned
  A worker's log file on disk is never deleted, but the pool's sweep prunes old entries
  from the worker registry. Resolving a step's log therefore cannot depend solely on a
  live registry entry surviving: once the registry entry for the worker that ran a step
  is gone, resolution falls back to reconstructing the log's path from the step's own
  durable role and the worker that claimed it, so a done step's log stays reachable
  regardless of registry churn.

  Background:
    Given a flow where the coder builds the item
    And the item "specs/login.md" is filed at step "build"

  @wip
  Scenario Outline: A step whose worker registry entry is still present resolves its log unchanged
    Given worker "sp1" has claimed and completed the build step with outcome "done"
    When the build step's log is resolved via <surface>
    Then the build step's log is found

    Examples:
      | surface             |
      | the trace read path |
      | the logs command    |

  @wip
  Scenario Outline: A done step whose worker registry entry has been pruned still resolves its log from disk
    Given worker "sp1" has claimed and completed the build step with outcome "done"
    And the worker registry no longer has an entry for worker "sp1"
    And worker "sp1"'s log file still exists on disk
    When the build step's log is resolved via <surface>
    Then the build step's log is found

    Examples:
      | surface             |
      | the trace read path |
      | the logs command    |

  @wip
  Scenario Outline: A pruned step whose log file is also gone from disk resolves to no log
    Given worker "sp1" has claimed and completed the build step with outcome "done"
    And the worker registry no longer has an entry for worker "sp1"
    And worker "sp1"'s log file does not exist on disk
    When the build step's log is resolved via <surface>
    Then the build step's log is not found

    Examples:
      | surface             |
      | the trace read path |
      | the logs command    |

  @wip
  Scenario Outline: A step that has never been claimed by a worker resolves to no log
    Given the build step has never been claimed by a worker
    When the build step's log is resolved via <surface>
    Then the build step's log is not found

    Examples:
      | surface             |
      | the trace read path |
      | the logs command    |

  @wip
  Scenario: Resolving a log by role alone never falls back past the live registry
    Given worker "sp1" has claimed and completed the build step with outcome "done"
    And the worker registry no longer has an entry for worker "sp1"
    And worker "sp1"'s log file still exists on disk
    When the log for role "coder" is resolved via the logs command
    Then the role's log is not found
