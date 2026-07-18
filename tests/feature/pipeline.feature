Feature: Work flows through the pipeline
  A item is filed at a step, claimed by the agent that owns that step, and
  completing it advances the work to the next step in the flow. This is the
  behavioural spec for the engine, independent of any implementation language.

  Background:
    Given a flow where the coder builds and the reviewer reviews

  Scenario: Filing an item creates a step for the entry step's agent
    When I file the item "specs/login.md" at step "build"
    Then there is one ready step for the coder

  Scenario: Claiming a ready step takes it off the queue
    Given the item "specs/login.md" is filed at step "build"
    When the coder claims the next step
    Then the claimed step is in progress
    And there are no ready steps for the coder

  Scenario: Completing a step advances the work to the next step
    Given the item "specs/login.md" is filed at step "build"
    And the coder has claimed the build step
    When the coder completes it with outcome "done"
    Then there is one ready step for the reviewer

  Scenario: An unknown outcome does not advance or close the step
    Given the item "specs/login.md" is filed at step "build"
    And the coder has claimed the build step
    When the coder completes it with outcome "banana"
    Then the command is rejected
    And there are no ready steps for the reviewer

  Scenario: A worker routes a step it does not own
    Given the item "specs/login.md" is filed at step "build"
    When a worker completes the ready build step with outcome "done"
    Then there is one ready step for the reviewer
