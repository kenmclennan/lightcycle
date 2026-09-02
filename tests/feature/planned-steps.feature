Feature: Planned-step projection from the workflow graph
  An item's remaining steps are not filed until the engine reaches them, so the
  Hierarchy view needs a read-only preview of what comes next. Reading an item's
  planned steps walks its pinned workflow graph forward from its current step,
  along the outcome that represents normal completion, without ever filing a
  real step.

  Scenario: A chain of single-outcome steps is projected in order
    Given a flow where the coder builds, the reviewer reviews, and the auditor audits
    And the item "specs/login.md" is filed at step "build"
    When the item's planned steps are read
    Then the planned steps are "review" for the agent, then "audit" for the agent

  Scenario: A step where a PR merging is distinct from its other outcomes projects only the merge path
    Given a flow where "await-merge" merges the item on outcome "merged", and its "changes" and "conflicted" outcomes loop back to earlier steps
    And the item "specs/login.md" is filed at step "await-merge"
    When the item's planned steps are read
    Then the planned steps are "cleanup" for the human
    And neither "changes" nor "conflicted" leads to a planned step

  Scenario: A step capped for repeated CI failure projects only the non-capped outcome
    Given a flow where "watch-ci" advances to "ready-merge" on outcome "done", and retries up to 3 times before escalating on outcome "ci-failed"
    And the item "specs/login.md" is filed at step "watch-ci"
    When the item's planned steps are read
    Then the planned steps are "ready-merge" for the human
    And the escalation step is not among the planned steps

  Scenario: Projection stops cleanly where the current step's outcome is declared terminal
    Given a flow where the reviewer's "done" outcome on step "review" closes the item with no further step
    And the item "specs/login.md" is filed at step "review"
    When the item's planned steps are read
    Then the planned steps are empty

  Scenario: Projection stops where the workflow does not name a single normal outcome
    Given a flow where "open-pr" can complete as "done" or "conflicted", with neither outcome backed by a merge or retry hook, and "done" leads to "watch-ci"
    And the item "specs/login.md" is filed at step "build", where "build" leads to "open-pr"
    When the item's planned steps are read
    Then the planned steps are "open-pr" for its owner, and nothing beyond it
    And reading the planned steps does not raise an error

  Scenario: A projected step's id continues the numbering after the steps already filed
    Given a flow where the coder builds, the reviewer reviews, and the auditor audits
    And the item "specs/login.md" completed step "build" and is now filed at step "review"
    When the item's planned steps are read
    Then the planned steps are "audit" for the agent
    And its id is the item's id with position 3, following the 2 steps already filed

  Scenario: Projected ids never collide with an already-filed step's id
    Given a flow where the coder builds, the reviewer reviews, and the auditor audits
    And the item "specs/login.md" completed step "build" and is now filed at step "review"
    When the item's planned steps are read
    Then none of the planned step ids match the id of the "build" step or the id of the "review" step

  Scenario Outline: An item with no live step has no planned steps
    Given the item "specs/login.md" <condition>
    When the item's planned steps are read
    Then the planned steps are empty

    Examples:
      | condition                                          |
      | has not been filed at any step yet                 |
      | has completed its last step on a terminal outcome  |

  Scenario: Reading planned steps never files a real step for the item
    Given a flow where the coder builds and the reviewer reviews
    And the item "specs/login.md" is filed at step "build"
    When the item's planned steps are read
    Then no new step has been filed for the item
