Feature: Work flows through the pipeline
  A story is filed at a step, claimed by the agent that owns that step, and
  completing it advances the work to the next step in the flow. This is the
  behavioural spec for the engine, independent of any implementation language.

  Background:
    Given a flow where the coder builds and the reviewer reviews

  Scenario: Filing a story creates a task for the entry step's agent
    When I file the story "specs/login.md" at step "build"
    Then there is one ready task for the coder

  Scenario: Claiming a ready task takes it off the queue
    Given the story "specs/login.md" is filed at step "build"
    When the coder claims the next task
    Then the claimed task is in progress
    And there are no ready tasks for the coder

  Scenario: Completing a task advances the work to the next step
    Given the story "specs/login.md" is filed at step "build"
    And the coder has claimed the build task
    When the coder completes it with outcome "done"
    Then there is one ready task for the reviewer

  Scenario: An unknown outcome does not advance or close the task
    Given the story "specs/login.md" is filed at step "build"
    And the coder has claimed the build task
    When the coder completes it with outcome "banana"
    Then the command is rejected
    And there are no ready tasks for the reviewer
