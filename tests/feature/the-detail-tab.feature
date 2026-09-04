Feature: The Detail tab
  A step's Detail tab shows its full record - everything the step carries
  beyond what the header or a hierarchy row already shows. Its PR and branch
  lead, since that is what a human opening a step for review came for; both
  live on the step's phase run in storage, but the view shows them as
  unambiguously the step's own, never naming "phase run" or "pass". After
  them follow stage, state, role, model, claimed_by, outcome, notes, park
  (needs / reason / tried), reflection, and watched_step. `tried` has never
  been shown anywhere in the TUI before this tab. A field with nothing
  recorded is omitted rather than shown blank. An item has no step record of
  its own, so it has no Detail tab. A parked step can also be resumed from
  here with a dedicated keypress, replacing the header's old copy-pasteable
  resume command; it succeeds only when the step's stage is workflow-declared
  agent-owned, and surfaces failure rather than crashing when it isn't. It
  does nothing on a node that isn't a parked step.

  @wip
  Scenario: A step's PR and branch are shown first, ahead of every other field
    Given a step whose phase run has a branch and a PR
    When I open its Detail tab
    Then its PR and branch are shown before stage, state, role, model, claimed_by, outcome, notes, park, reflection, and watched_step

  @wip
  Scenario: A step's branch and PR are shown as unambiguously its own
    Given a step whose phase run has a branch and a PR
    When I open its Detail tab
    Then the branch and the PR are shown
    And neither the words "phase run" nor "pass" appear anywhere on the tab

  @wip
  Scenario Outline: Confirming a step's PR opens it, the same keypress the Artifacts list uses for a URL
    Given a step whose phase run has a PR, its Detail tab open, the PR field selected
    When <key> is pressed
    Then the PR opens in the browser

    Examples:
      | key   |
      | Enter |
      | →     |

  @wip
  Scenario: A code-await-merge step's PR is on screen the moment its hub opens, with no further navigation
    Given a step at stage "code-await-merge" whose phase run has a PR
    When I open its hub
    Then it lands on the Detail tab
    And the PR is shown on screen

  @wip
  Scenario: A step with no branch or PR on its phase run shows neither field
    Given a step whose phase run has no branch and no PR
    When I open its Detail tab
    Then no branch field is shown
    And no PR field is shown

  @wip
  Scenario: The Detail tab shows the step's stage, state, role, and model
    Given a step with a stage, a state, a role, and a model
    When I open its Detail tab
    Then its stage, its state, its role, and its model are all shown

  @wip
  Scenario: The Detail tab shows the step's claimed_by, outcome, and notes
    Given a step with a claimed_by, an outcome, and notes recorded
    When I open its Detail tab
    Then its claimed_by, its outcome, and its notes are all shown

  @wip
  Scenario: The Detail tab shows the step's reflection and watched_step
    Given a step with a reflection and a watched_step recorded
    When I open its Detail tab
    Then its reflection and its watched_step are both shown

  @wip
  Scenario: The Detail tab shows the step's park fields - needs, reason, and tried
    Given a step parked with a needs, a reason, and a tried all recorded
    When I open its Detail tab
    Then the park's needs, its reason, and its tried are all shown

  @wip
  Scenario: The tried field is shown on Detail, the only place it has ever been shown
    Given a step parked with a tried recorded
    When I open its Detail tab
    Then the recorded tried text is shown

  @wip
  Scenario: A field with nothing recorded is omitted, not shown blank
    Given a step with no outcome, no notes, no reflection, and no watched_step recorded
    When I open its Detail tab
    Then no outcome field is shown
    And no notes field is shown
    And no reflection field is shown
    And no watched_step field is shown

  @wip
  Scenario: Resuming a parked step whose stage the workflow declares agent-owned succeeds and shows a confirmation toast
    Given a step parked at a stage the workflow declares agent-owned, its hub open
    When r is pressed
    Then a brief confirmation toast is shown
    And the step's role is reassigned to its workflow-declared owner
    And its park fields are cleared

  @wip
  Scenario: Resuming a step parked at a stage the workflow declares human-owned fails and leaves it unchanged
    Given a step parked at a stage the workflow declares human-owned, its hub open
    When r is pressed
    Then a clear message is shown, not a silent failure
    And the step's role and park fields are unchanged

  @wip
  Scenario: The resume key does nothing on an item, since only a step can be resumed
    Given an item, its hub open
    When r is pressed
    Then nothing happens, since there is no step to resume
    And no toast is shown

  @wip
  Scenario: The resume key does nothing on a step that isn't parked
    Given a step with no park recorded, its hub open
    When r is pressed
    Then nothing happens, since there is nothing parked to resume
    And no toast is shown

  @wip
  Scenario: An item has no Detail tab
    Given an item, its hub open
    Then no Detail tab is shown
