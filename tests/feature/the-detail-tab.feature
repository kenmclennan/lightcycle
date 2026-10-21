Feature: The Detail tab
  A step in a run always leads its Detail tab with the run rows - its PR,
  branch and worktree - and a step's `detail:` front matter list adds to them,
  a name in both shown once, leading. A step with no run shows the list its
  stage declares, or the default list of its outcome and report when it
  declares none, with its needs and reason when it is parked. Entries are resolved by the engine,
  so the tab carries no field list of its own, and an entry shows its recorded
  value or stays blank. A step's PR is shown as unambiguously its own, never
  naming "phase run" or "pass". Opening the worktree, unlike the PR,
  hands it to the configured editor rather than a browser. An item has no step record of its
  own, so it has no Detail tab. A parked step can also be resumed from here
  with a dedicated keypress; it succeeds only when the step's stage is
  workflow-declared agent-owned, and surfaces failure rather than crashing
  when it isn't. It does nothing on a node that isn't a parked step.

  Scenario: A step closed with a report shows its outcome and report first by default
    Given a step with an outcome and a report recorded
    When I open its Detail tab
    Then its outcome and its report are shown, in that order, at the top

  Scenario: A step whose phase run has a PR leads with the run rows before the outcome and report
    Given a step whose phase run has a branch and a PR
    When I open its Detail tab
    Then the run rows lead, followed by the outcome and the report
    And neither the words "phase run" nor "pass" appear anywhere on the tab

  Scenario Outline: Confirming a step's PR opens it, the same keypress the Artifacts list uses for a URL
    Given a step whose phase run has a PR, its Detail tab open, the PR field selected
    When <key> is pressed
    Then the PR opens in the browser

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: A code-await-merge step's hub opens on Detail, with its PR shown
    Given a step at stage "code-await-merge" whose phase run has a PR
    When I open its hub
    Then it lands on the Detail tab
    And the PR is shown on screen

  Scenario: A human step with no run opens on Detail, with no PR field shown
    Given a parked human step whose phase run has no branch and no PR
    When I open its hub
    Then it lands on the Detail tab
    And no PR field is shown

  Scenario: A step with no run shows no PR field
    Given a step whose phase run has no branch and no PR
    When I open its Detail tab
    Then no PR field is shown

  Scenario: The default list for a step in a run shows the branch and the worktree
    Given a step whose phase run has a branch, in a resolvable repo
    When I open its Detail tab
    Then a branch field is shown
    And the worktree is shown

  Scenario: A step declaring its own detail list gets the run rows first and the declared entries after
    Given a step declaring the detail list branch, worktree and pr, whose phase run has a branch and a PR, in a resolvable repo
    When I open its Detail tab
    Then its Detail entries are pr, branch and worktree, in that order
    And the worktree is shown

  Scenario: The worktree entry is blank when its repo cannot be resolved
    Given a step declaring the detail list branch and worktree, whose phase run has a branch, in an unresolvable repo
    When I open its Detail tab
    Then the worktree entry is shown blank

  Scenario Outline: Confirming a declared worktree entry opens it in the configured editor
    Given a step declaring the detail list branch, worktree and pr, whose phase run has a branch and a PR, in a resolvable repo, its Detail tab open, the worktree field selected
    When <key> is pressed
    Then the worktree opens in the editor

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: A parked step shows its needs and reason by default
    Given a step parked with a needs and a reason recorded
    When I open its Detail tab
    Then the park's needs and its reason are shown

  Scenario: A step that is not parked shows neither needs nor reason
    Given a step with no park recorded, its hub open
    When I open its Detail tab
    Then no needs field is shown
    And no reason field is shown

  Scenario: Resuming a parked step whose stage the workflow declares agent-owned succeeds and shows a confirmation toast
    Given a step parked at a stage the workflow declares agent-owned, its hub open
    When r is pressed
    Then a brief confirmation toast is shown
    And the step's role is reassigned to its workflow-declared owner
    And its park fields are cleared

  Scenario: Resuming a step parked at a stage the workflow declares human-owned fails and leaves it unchanged
    Given a step parked at a stage the workflow declares human-owned, its hub open
    When r is pressed
    Then a clear message is shown, not a silent failure
    And the step's role and park fields are unchanged

  Scenario: The resume key does nothing on an item, since only a step can be resumed
    Given an item, its hub open
    When r is pressed
    Then nothing happens, since there is no step to resume
    And no toast is shown

  Scenario: The resume key does nothing on a step that isn't parked
    Given a step with no park recorded, its hub open
    When r is pressed
    Then nothing happens, since there is nothing parked to resume
    And no toast is shown

  Scenario: An item has no Detail tab
    Given an item, its hub open
    Then no Detail tab is shown
