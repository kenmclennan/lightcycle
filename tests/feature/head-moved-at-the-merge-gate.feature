Feature: A head that moves under a merge gate returns the item to CI
  An item waiting at a merge gate always means CI is green on the PR's current head.

  Scenario: A pushed head completes the gate with the declared outcome
    Given an item waits at a gate declaring pr_head_moved with outcome head-moved
    And the gate has seen the PR head
    When the PR head changes
    And the monitor runs
    Then the gate step is done
    And the monitor reports the item as head-moved

  Scenario: Update-branch as the cause gives the same result
    Given an item waits at a gate declaring pr_head_moved with outcome head-moved
    And the PR is behind a base that requires an up-to-date branch
    When the monitor runs
    And the monitor runs
    Then the gate step is done
    And the monitor reports the item as head-moved

  Scenario: A gate without the hook stays and keeps the update-branch note
    Given an item waits at a gate that does not declare pr_head_moved
    And the PR is behind a base that requires an up-to-date branch
    When the monitor runs
    And the monitor runs
    Then the gate step is not done
    And the gate step carries the update-branch note

  Scenario: A merged PR resolves merged and never head-moved
    Given an item waits at a gate declaring pr_head_moved with outcome head-moved
    And the gate has seen the PR head
    When the PR head changes
    And the PR is merged
    And the monitor runs
    Then the gate step is done
    And the monitor reports the item as merged
    And the monitor does not report the item as head-moved
