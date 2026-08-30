Feature: Closing and reopening an item
  Closing an item files an outcome and force-closes whatever children remain
  open beneath it; reopening a closed item clears that outcome and its close
  time so the item's state rolls up fresh from its children again, but
  otherwise leaves those children exactly as they were - refiling the step
  the flow should resume at is a second, separate action.

  Background:
    Given a flow where the coder builds and the reviewer reviews

  @wip
  Scenario: An item moves from backlogged, through ready and in progress, to done
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    Then the item is backlogged
    When I activate the item
    Then the item is ready
    When the coder claims the next step
    Then the item is in progress
    When I close the item with outcome "done"
    Then the build step is done with outcome "done"
    And the item is done with outcome "done"

  @wip
  Scenario: Closing an item force-closes a step that is still open, carrying the item's own outcome, but leaves an already-finished step's own outcome untouched
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have activated the item
    And the coder has completed the build step with outcome "done"
    When I close the item with outcome "abandoned"
    Then the build step is done with outcome "done"
    And the review step is done with outcome "abandoned"
    And the item is done with outcome "abandoned"

  @wip
  Scenario: Closing a step that is still claimed by a worker, by closing its item, closes it too, with the item's outcome
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have activated the item
    And the coder has completed the build step with outcome "done"
    And the reviewer has claimed the review step
    When I close the item with outcome "abandoned"
    Then the build step is done with outcome "done"
    And the review step is done with outcome "abandoned"
    And the item is done with outcome "abandoned"

  @wip
  Scenario: An item that was never activated closes cleanly
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    When I close the item with outcome "wontfix"
    Then the item is done with outcome "wontfix"

  @wip
  Scenario: Closing an item that is already closed does not overwrite its recorded outcome
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have closed the item with outcome "wontfix"
    When I close the item with outcome "abandoned"
    Then the item is done with outcome "wontfix"

  @wip
  Scenario: Reopening a closed item that never had any children returns it straight to the backlog
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have closed the item with outcome "wontfix"
    When I reopen the item
    Then the item's outcome and close time are cleared
    And the item is backlogged

  @wip
  Scenario: Reopening a closed item whose old children are still done does not, by itself, change what it reports
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have activated the item
    And the coder has completed the build step with outcome "done"
    And I have closed the item with outcome "shipped"
    When I reopen the item
    Then the item's outcome and close time are cleared
    And the item is done

  @wip
  Scenario: Filing a new step under a reopened item reports it as in progress immediately, before anyone claims the new step
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have activated the item
    And the coder has completed the build step with outcome "done"
    And I have closed the item with outcome "shipped"
    And I have reopened the item
    When a step is filed directly against the item
    Then the item's outcome and close time are cleared
    And the item is in progress

  @wip
  Scenario: Re-activating a reopened item through the normal activation path is refused
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have activated the item
    And the coder has completed the build step with outcome "done"
    And I have closed the item with outcome "shipped"
    And I have reopened the item
    When I activate the item
    Then the command is rejected

  @wip
  Scenario: Reopening a step directly is refused, distinctly from reopening an item
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have activated the item
    And the coder has completed the build step with outcome "done"
    When I reopen the build step
    Then the command is rejected
    And the refusal names "--state ready" as the way to hand a step back to its lane

  @wip
  Scenario: Reopening a node that has never been closed is refused
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    When I reopen the item
    Then the command is rejected
    And the refusal names the item's current state
