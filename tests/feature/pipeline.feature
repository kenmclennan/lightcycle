Feature: Work flows through the pipeline
  A item is filed at a stage, claimed by any agent worker, and completing it
  advances the work to the next stage in the flow. This is the
  behavioural spec for the engine, independent of any implementation language.

  Background:
    Given a flow where the coder builds and the reviewer reviews

  Scenario: Filing an item creates a ready agent step at the entry stage
    When I file the item "specs/login.md" at step "build"
    Then there is one ready agent step at the "build" stage

  Scenario: Claiming a ready step takes it off the queue
    Given the item "specs/login.md" is filed at step "build"
    When an agent claims the next step
    Then the claimed step is in progress
    And there are no ready agent steps

  Scenario: Completing a step advances the work to the next step
    Given the item "specs/login.md" is filed at step "build"
    And an agent has claimed the build step
    When that agent completes it with outcome "done"
    Then there is one ready agent step at the "review" stage

  Scenario: An unknown outcome does not advance or close the step
    Given the item "specs/login.md" is filed at step "build"
    And an agent has claimed the build step
    When that agent completes it with outcome "banana"
    Then the command is rejected
    And there is no ready agent step at the "review" stage

  Scenario: A worker routes a step it does not own
    Given the item "specs/login.md" is filed at step "build"
    When a worker completes the ready build step with outcome "done"
    Then there is one ready agent step at the "review" stage
