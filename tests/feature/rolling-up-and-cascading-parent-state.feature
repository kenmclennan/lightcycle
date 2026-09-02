Feature: Rolling up and cascading parent state
  An item's own state rolls up from its steps: no steps reports backlogged,
  and any step in progress reports in progress. Completing a workflow's
  terminal step closes its item with no separate close command issued
  anywhere. A sibling item is left exactly as it was.

  Scenario: An item with no steps reports backlogged
    Given a flow where the coder builds and the reviewer reviews
    And an item with no steps
    Then the item is backlogged

  Scenario: An item with one step in progress reports in progress
    Given a flow where the coder builds and the reviewer reviews
    And an item with that workflow
    And I have activated the item
    When the coder claims the next step
    Then the item is in progress

  Scenario: Completing a workflow's terminal step closes its item automatically, with no separate close command issued
    Given a flow whose entry step is also its terminal step
    And an item with that workflow
    And I have activated the item
    When I complete the item's only step with outcome "done"
    Then the item is done

  Scenario: Completing a step that is not the workflow's terminal step leaves the item open
    Given a flow where the coder builds and the reviewer reviews
    And an item with that workflow
    And I have activated the item
    When the coder claims the next step
    And the coder completes the build step with outcome "done"
    Then the item is in progress

  Scenario: A second, still-open item is untouched when the first item's terminal step closes it
    Given a flow whose entry step is also its terminal step
    And two items, both with that workflow
    And I have activated both items
    When I complete the first item's only step with outcome "done"
    Then the first item is done
    And the second item is ready
