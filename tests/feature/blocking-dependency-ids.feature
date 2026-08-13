Feature: Blocking-dependency ids on the live read path
  Every live read that hydrates a node already reports how many unresolved
  dependencies block it, as a bare count. This adds the blocking nodes' own
  ids alongside that count, so a caller can name which node is doing the
  blocking, not just how many there are. The count keeps its existing
  meaning and value throughout - the blocking ids are additive, never a
  replacement for it.

  Scenario: A step blocked by one dependency names that dependency's id
    Given a step "blocked" needs a step "dep1"
    When "blocked" is read
    Then its blocking ids are "dep1"
    And its dependency count is 1

  Scenario: A step blocked by more than one dependency names all of them
    Given a step "blocked" needs steps "dep1" and "dep2"
    When "blocked" is read
    Then its blocking ids are "dep1" and "dep2", in either order
    And its dependency count is 2

  Scenario: Closing one of several dependencies drops only that one from the blocking ids
    Given a step "blocked" needs steps "dep1" and "dep2"
    And "dep1" is closed
    When "blocked" is read
    Then its blocking ids are "dep2"
    And its dependency count is 1

  Scenario: Deleting a dependency drops it from the blocking ids, not just the count
    Given a step "blocked" needs a step "dep1"
    And "dep1" is deleted
    When "blocked" is read
    Then its blocking ids are empty
    And its dependency count is 0

  Scenario: A step with no dependencies has no blocking ids
    Given a step "blocked" with no dependencies
    When "blocked" is read
    Then its blocking ids are empty
    And its dependency count is 0
