Feature: Activating an item hands it to the pool
  Activating an item resolves the workflow it is pinned to and files that
  workflow's entry step for the role that owns it, immediately ready for the
  pool to claim. Every
  requirement is checked before anything is written: a refusal, for any
  reason, leaves the item exactly as it was - still backlogged, with no step
  filed.

  Background:
    Given a flow where the coder builds and the reviewer reviews

  Scenario: Activating an item with no step named files the workflow's entry stage, owned by the agent role, ready immediately
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    When I activate the item
    Then the entry step is the "build" stage, owned by the agent role
    And it is ready

  Scenario: The step activation produces can be claimed by the pool
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have activated the item
    When an agent claims the next step
    Then the claimed step is in progress

  Scenario: Activation refuses to file a step when the workflow itself requires an artifact the item does not have
    Given a workflow "lightcycle/spec-driven" that requires a design
    And an item with that workflow, with no design attached
    When I activate the item
    Then the command is rejected
    And the item is still backlogged, with no step filed

  Scenario: Activation refuses to file a step when the entry step's own contract requires an artifact the item does not have
    Given a workflow "lightcycle/spec-driven" whose entry step requires a spec
    And an item with that workflow, with no spec attached
    When I activate the item
    Then the command is rejected
    And the item is still backlogged, with no step filed

  Scenario: Activation refuses an explicit step name the workflow does not own
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    When I activate the item at step "no-such-step"
    Then the command is rejected
    And the item is still backlogged, with no step filed

  Scenario: Activation refuses a node that is not an item
    Given a step
    When I activate the step
    Then the command is rejected

  Scenario: Re-activating an item that already has a step filed under it is refused
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have activated the item
    When I activate the item again
    Then the command is rejected
    And the item still has exactly one step filed

  Scenario: An explicit workflow at activation overrides the item's own pin
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And a second workflow "lightcycle/reviews-first" in the same origin, entering at a different stage
    When I activate the item with workflow "lightcycle/reviews-first"
    Then the entry step is the "review" stage, not "build"
    And the item is pinned to the "lightcycle/reviews-first" workflow, not to "lightcycle/spec-driven"

  Scenario: Activation fails when the item carries no workflow
    Given an item with no workflow, and a spec attached
    When I activate the item
    Then the command is rejected
    And the item is still backlogged, with no step filed

  Scenario Outline: An unresolvable workflow selector fails activation immediately, before anything is written
    Given an item with workflow "<selector>", with a spec attached
    When I activate the item
    Then the command is rejected
    And the item is still backlogged, with no step filed

    Examples:
      | selector                     |
      | spec-driven                  |
      | unknown-origin/spec-driven   |
      | lightcycle/no-such-workflow  |
