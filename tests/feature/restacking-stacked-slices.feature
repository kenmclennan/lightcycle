Feature: The engine retargets and restacks the slices of one item
  A sliced item is a stack of PRs, one per slice. When a slice merges, the slice
  above it is retargeted to the default branch and rebased. When a slice is
  reworked, the slices above it are rebased in stack order and pushed in one
  atomic operation, and a slice whose coder is still running waits.

  Scenario: A merged slice retargets the slice above it and restacks the next
    Given a three-slice item
    And slice 1 is squash-merged
    When the engine restacks
    Then slice 2's PR base is edited to the default branch before the rebase
    And one restack moves slices 2 and 3 in stack order
    And only slice 2 is marked retargeted
    And slice 2 is told its head moved
    And a second pass does not restack again

  Scenario: A reworked slice restacks the slice above and defers the one being coded
    Given a three-slice item whose slice 3 coder is running
    And slice 1's head has moved
    When the engine restacks
    Then one restack moves slice 2 only
    And slice 3's step carries a deferral note
    And slice 3's branch is unmoved
    When slice 3 reaches its gate
    And the engine restacks
    Then the second restack moves slice 3 only

  Scenario: A conflict in slice 2 escalates once and leaves slice 3 unmoved
    Given a three-slice item
    And slice 1's head has moved
    And slice 2's rebase conflicts in "app.py"
    When the engine restacks
    Then slice 2's step is completed with the gave-up outcome naming "app.py"
    And slice 3's branch is unmoved
    And a second pass does not restack again

  Scenario: A conflict in slice 3 alone moves none of the plan
    Given a three-slice item
    And slice 1's head has moved
    And slice 3's rebase conflicts in "lib.py"
    When the engine restacks
    Then slice 3's step is completed with the gave-up outcome naming "lib.py"
    And slice 2's branch is unmoved
    And slice 3's branch is unmoved

  Scenario: The last slice of a two-slice item is retargeted with nothing above it
    Given a two-slice item
    And slice 1 is squash-merged
    When the engine restacks
    Then one restack moves slice 2 only
    And slice 2's PR base is edited to the default branch before the rebase

  Scenario: A child item stacked on a sliced item is restacked after its slices
    Given a three-slice item with a child item stacked on it
    And slice 1's head has moved
    When the engine restacks
    Then one restack moves slices 2 and 3 and the child item in order

  Scenario: A child item and the slice below it wait behind a running coder
    Given a three-slice item with a child item stacked on it whose slice 3 coder is running
    And slice 1's head has moved
    When the engine restacks
    Then one restack moves slice 2 only

  Scenario: Siblings above one slice move in slice order
    Given a four-slice item where slice 4 is stacked on slice 1
    And slice 1's head has moved
    When the engine restacks
    Then one restack moves slices 2, 3 and 4 in stack order

  Scenario: A deferred slice does not hold back its sibling
    Given a four-slice item where slice 4 is stacked on slice 1 and slice 2 coder is running
    And slice 1's head has moved
    When the engine restacks
    Then one restack moves slice 4 only

  Scenario: A slice created after its base merged is never retargeted
    Given a two-slice item whose slice 2 was created after slice 1 merged
    And slice 1 is squash-merged
    When the engine restacks
    Then nothing is restacked
    And no base edit is made
