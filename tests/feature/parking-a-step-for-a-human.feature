Feature: Parking a step for a human
  Blocking a step hands it from its owning role to the human role, carrying
  the question the human must decide as both the step's recorded need and a
  note explaining why it stopped. It is refused, with the step left exactly
  as it was, unless a question is stated - a human cannot be asked to decide
  nothing. A parked step then surfaces to the operator distinctly, with
  handing it back offered as one of its actions.

  Handing a parked step back to the pool is out of scope here and is not
  characterised by this file, in either direction.

  Background:
    Given a flow where the coder builds and the reviewer reviews

  Scenario: Blocking a step with no stated question is refused, and the step is left exactly as it was
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have activated the item
    And the coder has claimed the build step
    When I block the build step with no stated question
    Then the command is rejected
    And the build step's role is unchanged
    And the build step's state is unchanged
    And the build step's notes are unchanged

  Scenario: Blocking a step for a human hands it to the human role, and the step carries the stated question as both its recorded need and a note explaining why it stopped
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have activated the item
    And the coder has claimed the build step
    When I block the build step, asking the human to "pick a colour"
    Then the build step's role is human
    And the build step's need reads "pick a colour"
    And the build step's notes explain that it is blocked on "pick a colour"

  Scenario: A parked step appears in the operator's inbox, distinctly flagged, with handing it back offered as one of its actions
    Given an item with workflow "lightcycle/spec-driven", with a spec attached
    And I have activated the item
    And the coder has claimed the build step
    And I have blocked the build step, asking the human to "pick a colour"
    When I read the inbox
    Then the build step appears in the inbox with kind "blocked"
    And its offered actions include "unblock"
