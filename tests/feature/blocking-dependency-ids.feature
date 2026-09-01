Feature: Blocking-dependency ids on the live read path
  Every live read that hydrates a node already reports how many unresolved
  dependencies block it, as a bare count. This adds the blocking nodes' own
  ids alongside that count, so a caller can name which node is doing the
  blocking, not just how many there are. The count keeps its existing
  meaning and value throughout - the blocking ids are additive, never a
  replacement for it.

  A step with an unmet dependency is never claimed, by any role, and needs
  no action taken on it to become claimable again: the instant its last
  blocker closes, it is claimable. This holds whether it is held by one
  dependency or several, and holds independently of the blocking ids and
  count above - the two are meant to move together. A dependency-held step
  also sits with ordinary queued work, not in the human's inbox, the same
  as any other step waiting its turn.

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

  Scenario: Nothing claims a step held by an unmet dependency, even for the role that would otherwise own it
    Given a step "blocked", owned by the coder, needs a step "dep1"
    Then "blocked" is not ready for the coder to claim
    When the coder tries to claim the next step
    Then nothing is claimed

  Scenario: The moment a step's only dependency closes, the step becomes claimable with no action taken on the held step itself
    Given a step "blocked", owned by the coder, needs a step "dep1"
    And "dep1" is closed
    Then "blocked" is ready for the coder to claim
    When the coder claims the next step
    Then "blocked" is the step claimed

  Scenario: A step held by two dependencies is still un-claimable once only one has closed
    Given a step "blocked", owned by the coder, needs steps "dep1" and "dep2"
    And "dep1" is closed
    Then "blocked" is not ready for the coder to claim
    When the coder tries to claim the next step
    Then nothing is claimed

  Scenario: Closing the last of several dependencies releases the step for claiming
    Given a step "blocked", owned by the coder, needs steps "dep1" and "dep2"
    And "dep1" is closed
    And "dep2" is closed
    Then "blocked" is ready for the coder to claim
    When the coder claims the next step
    Then "blocked" is the step claimed

  Scenario: A step held by a dependency sits with ordinary queued work, not in the human's inbox
    Given a step "blocked" needs a step "dep1"
    Then "blocked" belongs to the queue lane, not the inbox lane

  Scenario: An item whose only step is held by an unmet dependency is ready, not backlogged
    Given an item whose only step "blocked" needs a step "dep1"
    Then the item containing "blocked" is ready
