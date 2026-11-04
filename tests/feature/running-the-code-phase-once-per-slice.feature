Feature: Running the code phase once per slice
  An item whose workflow declares a sliced phase and whose slices artifact lists several
  slices runs that phase once per slice, each slice stacked on the one below, and the item
  closes only when the last slice merges.

  Scenario: Three slices open three stacked slice runs
    Given a workflow whose code phase is sliced
    And an item with the slices "a", "b on a" and "c on b"
    When the item enters the code phase
    Then the item has three open slice runs in slice order
    And the first slice's write step is claimable
    And the second and third slices' write steps are blocked on the item

  Scenario: The next slice is released when the slice below holds a PR
    Given a workflow whose code phase is sliced
    And an item with the slices "a", "b on a" and "c on b"
    And the item has entered the code phase
    When slice 1's run gets a PR and a tick runs
    Then the second slice's write step is claimable
    And the third slice's write step is still blocked
    And the second slice's step stacks on the first slice's branch and PR

  Scenario: A slice with a branch but no PR does not release the slice above
    Given a workflow whose code phase is sliced
    And an item with the slices "a", "b on a" and "c on b"
    And the item has entered the code phase
    When slice 1's run gets a branch and a tick runs
    Then the second slice's write step is still blocked

  Scenario: The item closes only after the last slice merges
    Given a workflow whose code phase is sliced
    And an item with the slices "a", "b on a" and "c on b"
    And the item has entered the code phase
    And every slice has reached its merge gate
    When the slices merge in order 1, 2 and 3
    Then cleanup ran once
    And the item closed only after the third merge

  Scenario: Slices merged in inverted order still run cleanup once
    Given a workflow whose code phase is sliced
    And an item with the slices "a", "b on a" and "c on b"
    And the item has entered the code phase
    And every slice has reached its merge gate
    When the slices merge in order 3, 2 and 1
    Then cleanup ran once
    And the item closed only after the third merge

  Scenario: The inbox groups the merge gates under the item bottom-up
    Given a workflow whose code phase is sliced
    And an item with the slices "a", "b on a" and "c on b"
    And the item has entered the code phase
    And every slice has reached its merge gate
    When I list the inbox
    Then the inbox shows the item once with three gates in slice order
    And showing the item lists three slices in slice order

  Scenario: Rework in a slice stays inside that slice
    Given a workflow whose code phase is sliced
    And an item with the slices "a", "b on a" and "c on b"
    And the item has entered the code phase
    And every slice has reached its merge gate
    When the second slice's gate asks for changes
    Then a new write step exists in slice 2
    And slices 1 and 3 keep their gates and open runs

  Scenario: A single-line slices artifact runs unsliced
    Given a workflow whose code phase is sliced
    And an item with the single slice "only"
    When the item enters the code phase
    Then the item has one open run with slice 0

  Scenario: No slices artifact runs unsliced
    Given a workflow whose code phase is sliced
    And an item with no slices artifact
    When the item enters the code phase
    Then the item has one open run with slice 0

  Scenario: A malformed slices artifact is refused at attach
    Given a workflow whose code phase is sliced
    And an item with no slices artifact
    When I attach the slices "b on a" to the item
    Then the attach is refused naming the line
    And the item has no slices artifact
