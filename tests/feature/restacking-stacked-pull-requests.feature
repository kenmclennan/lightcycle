Feature: The engine retargets and restacks stacked pull requests
  When a parent item's PR squash-merges, each child PR is retargeted to the
  default branch and rebased onto it. When a parent's branch moves after rework,
  every descendant is rebased onto the new head and pushed in one atomic
  operation, with a lease on each branch.

  Scenario: A parent squash-merge retargets the child onto the default branch
    Given a parent with a child stacked on it
    And the parent's PR is squash-merged
    When the engine restacks
    Then the child's PR base is edited to the default branch before the rebase
    And the child is rebased onto the default branch with a lease
    And the child no longer stacks on the parent
    And the child's diff against the default branch is its own commits only

  Scenario: A parent rework restacks two children and a grandchild together
    Given a parent with two children and a grandchild stacked on the first child
    And the parent's head has moved
    When the engine restacks
    Then one restack moves three branches in stack order
    And every branch of the stack has a new tip
    And the first child's gate step is told the head moved

  Scenario: A stale lease moves none of the branches and parks the named child
    Given a parent with two children and a grandchild stacked on the first child
    And the parent's head has moved
    And the grandchild's branch has moved on origin
    When the engine restacks
    Then no branch of the stack has a new tip
    And the grandchild's step is parked naming its branch

  Scenario: A rebase conflict escalates the gate to review-conflict
    Given a parent with a child stacked on it
    And the parent's head has moved
    And the child's rebase conflicts in "app.py"
    When the engine restacks
    Then the child's step is completed with the gave-up outcome naming "app.py"
    And no branch of the stack has a new tip
    And a second pass does not restack again

  Scenario: A conflict in the grandchild alone leaves the whole stack unmoved
    Given a parent with a child and a grandchild stacked on the child
    And the parent's head has moved
    And the grandchild's rebase conflicts in "lib.py"
    When the engine restacks
    Then the grandchild's step is completed with the gave-up outcome naming "lib.py"
    And no branch of the stack has a new tip
    And the child's step is untouched

  Scenario: An auto-retargeted PR needs no base edit
    Given a parent with a child stacked on it
    And the parent's PR is squash-merged
    And the child's PR already targets the default branch
    When the engine restacks
    Then no base edit is made
    And the child is rebased onto the default branch with a lease

  Scenario: A head equal to the recorded base does nothing
    Given a parent with a child stacked on it
    And the child's recorded base equals the parent's head
    When the engine restacks
    Then nothing is restacked

  Scenario: A head one sha away from the recorded base restacks
    Given a parent with a child stacked on it
    And the parent's head has moved
    When the engine restacks
    Then one restack moves one branch

  Scenario Outline: A plan with an unsettled node is deferred and touches nothing
    Given a parent with a child stacked on it
    And the parent's head has moved
    And the child <problem>
    When the engine restacks
    Then nothing is restacked
    And the child's step carries a deferral note

    Examples:
      | problem                       |
      | has a running worker step     |
      | has an uncommitted worktree   |
      | has no PR yet                 |
      | has no branch on origin       |

  Scenario: After a push the moved PRs are marked stale
    Given a parent with a child stacked on it
    And the parent's head has moved
    When the engine restacks
    Then the child's PR snapshot entry is marked stale
