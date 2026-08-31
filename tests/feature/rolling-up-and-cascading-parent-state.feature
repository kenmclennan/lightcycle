Feature: Rolling up and cascading parent state
  A theme's own state rolls up from its children the same way an item's
  does: no children reports backlogged, and any child in progress reports
  in progress. Completing a workflow's terminal step closes its item with
  no separate close command issued anywhere, and the same cascade
  continues upward - the moment an item's terminal step leaves its theme
  with none of its other items still open, the theme closes too, again
  with no separate close command. A theme with any other item still open
  is left exactly as it was.

  @wip
  Scenario: A theme with no items reports backlogged
    Given a flow where the coder builds and the reviewer reviews
    And a theme with no items
    Then the theme is backlogged

  @wip
  Scenario: A theme with one item in progress reports in progress
    Given a flow where the coder builds and the reviewer reviews
    And an item under a theme, with that workflow
    And I have activated the item
    When the coder claims the next step
    Then the theme is in progress

  @wip
  Scenario: Completing a workflow's terminal step closes its item automatically, with no separate close command issued
    Given a flow whose entry step is also its terminal step
    And an item under a theme, with that workflow
    And I have activated the item
    When I complete the item's only step with outcome "done"
    Then the item is done with outcome "done"

  @wip
  Scenario: Completing a step that is not the workflow's terminal step leaves the item open
    Given a flow where the coder builds and the reviewer reviews
    And an item under a theme, with that workflow
    And I have activated the item
    When the coder claims the next step
    And the coder completes the build step with outcome "done"
    Then the item is in progress

  @wip
  Scenario: Closing the last open item under a theme, by completing that item's terminal step, cascades to close the theme too
    Given a flow whose entry step is also its terminal step
    And an item under a theme, with that workflow
    And I have activated the item
    When I complete the item's only step with outcome "done"
    Then the item is done with outcome "done"
    And the theme is done

  @wip
  Scenario: A theme with a second, still-open item stays open when the first item's terminal step closes it
    Given a flow whose entry step is also its terminal step
    And two items under the same theme, both with that workflow
    And I have activated both items
    When I complete the first item's only step with outcome "done"
    Then the first item is done with outcome "done"
    And the second item is ready
    And the theme is in progress
