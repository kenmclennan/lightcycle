Feature: An item can be stacked on a parent item
  An item activated with --stacks-on waits until the parent's stack run holds a
  PR, then is released within one tick and reads the parent's branch and PR off
  lc show. A refusal leaves the item exactly as it was.

  Background:
    Given a workflow whose build phase runs in the project repo
    And a parent item whose build run has a branch but no PR

  Scenario: Activating stacked blocks the first step until the parent's PR exists
    When I activate a child stacked on the parent
    Then the child's first step is blocked by the parent
    And the child is recorded as stacked on the parent

  Scenario: The parent's PR releases the child within one tick
    Given I have activated a child stacked on the parent
    When the parent's build run gets a PR and a tick runs
    Then the child's first step is claimable

  Scenario: lc show reports the relation on both items and the stack on the step
    Given I have activated a child stacked on the parent
    And the parent's build run gets a PR and a tick runs
    When I show the child's first step
    Then the step's stack names the parent, its title, its branch and its PR
    And showing the child reports it is stacked on the parent
    And showing the parent lists the child as stacked on it

  Scenario: A step in the specs repo reports no stack
    Given I have activated a child stacked on the parent
    When I show a specs-workspace step of the child
    Then the step reports no stack

  Scenario: Stacking together with depends is refused and nothing is written
    When I activate a child stacked on the parent and depending on another item
    Then the command is rejected naming both flags
    And the child is still backlogged, with no step filed
