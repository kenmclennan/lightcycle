Feature: The node hub
  Opening any node - theme, item, or step - lands on the hub: a fixed header
  above four tabs (Description, Hierarchy, Log, Artifacts), landing on
  whichever tab matches the node's current status. The header stays fixed
  while ] and [ cycle the tabs; Tab keeps its own global meaning, jumping
  straight to the backlog (or back to current work) from any tab, at any
  depth, without first backing out through Esc. Closing the hub always
  returns to wherever it was opened from - the priority list or the backlog
  - at the same position. Each tab's own content beyond this shared shell is
  specified in its own feature file - Description, Hierarchy, Log, and
  Artifacts alike.

  Scenario Outline: Confirming a selected row opens its hub, replacing the list
    Given the priority list is showing with an item
    When I select that item's row
    And <key> is pressed
    Then the item's hub opens, replacing the list on screen

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: The header shows the item's identity
    Given an item with a project, a theme, and a workflow
    When I open it with Enter or →
    Then the header shows its id, its title, its project, its theme, and its workflow

  Scenario: An item with no theme shows no theme line
    Given an item with no theme
    When I open it with Enter or →
    Then no theme line is shown in the header

  Scenario: An item with no workflow shows no workflow line
    Given an item with no workflow
    When I open it with Enter or →
    Then no workflow line is shown in the header

  Scenario: The header names the current step
    Given an item at step "write-code"
    When I open it with Enter or →
    Then the header names "write-code" as the current step

  Scenario: The header shows the role performing the current step
    Given an item at step "write-code" performed by the role "write-code"
    When I open it with Enter or →
    Then the header shows "write-code" as the role

  Scenario: An active item's header shows its elapsed time, matching the list's own format
    Given an active item at step "build" claimed 14 minutes ago
    When I open it with Enter or →
    Then the header's elapsed time reads "14m"

  Scenario: A human step with no worker shows no role and no elapsed time
    Given an item at a human step, with no worker
    When I open it with Enter or →
    Then no role is shown in the header
    And no elapsed time is shown in the header

  Scenario: A selected step's header shows its role and state, not theme or workflow
    Given a step is selected, rather than an item or theme
    When I open it with Enter or →
    Then the header shows its role and its state
    And no theme or workflow fields are shown

  Scenario Outline: A fieldset field's key stays dim while its value renders at full text brightness
    Given <given>
    When I open it with Enter or →
    Then the header's "<key>" key is shown in the dim colour
    And the header's "<key>" value is shown in the text colour

    Examples:
      | given                                                              | key     |
      | an item at step "write-code"                                       | STEP    |
      | an item at step "write-code" performed by the role "write-code"    | ROLE    |
      | an active item at step "build" claimed 14 minutes ago              | ELAPSED |
      | a step is selected, rather than an item or theme                   | STATE   |

  Scenario: A theme's header is its id, its title, and its item count - nothing else
    Given a theme with 4 items underneath
    When I open it with Enter or →
    Then the header shows "theme · 4 items underneath"
    And no project, theme, or workflow line is shown in the header

  Scenario: A theme's header shows no project line, even when its items belong to different projects
    Given a theme whose items belong to different projects
    When I open it with Enter or →
    Then no project line is shown in the header

  Scenario Outline: Opening a node lands on the tab that matches its status
    Given a node with the status "<status>"
    When I open it with Enter or →
    Then it lands on the "<tab>" tab

    Examples:
      | status                                | tab       |
      | active                                | Log       |
      | needs-attention on a human step       | Artifacts |
      | blocked on another item's completion  | Hierarchy |
      | queued, not yet run                   | Hierarchy |
      | done                                  | Artifacts |
      | a theme                               | Hierarchy |

  Scenario Outline: ] cycles forward through the four tabs, wrapping back to Description
    Given a node's hub is open, on the "<from>" tab
    When ] is pressed
    Then the "<to>" tab becomes active

    Examples:
      | from        | to          |
      | Description | Hierarchy   |
      | Hierarchy   | Log         |
      | Log         | Artifacts   |
      | Artifacts   | Description |

  Scenario Outline: [ cycles backward through the same four tabs, in reverse
    Given a node's hub is open, on the "<from>" tab
    When [ is pressed
    Then the "<to>" tab becomes active

    Examples:
      | from        | to          |
      | Description | Artifacts   |
      | Artifacts   | Log         |
      | Log         | Hierarchy   |
      | Hierarchy   | Description |

  Scenario Outline: Tab jumps straight to the backlog from any tab in an open node's hub, without cycling tabs
    Given the priority list is showing with an item
    When I open it with Enter or →
    And the "<tab>" tab is active
    And Tab is pressed
    Then the backlog is shown in place of the hub

    Examples:
      | tab         |
      | Hierarchy   |
      | Log         |
      | Artifacts   |
      | Description |

  Scenario: Tab jumps straight back to current work from a node opened out of the backlog
    Given the backlog is showing with a todo item
    When I open it with Enter or →
    And Tab is pressed
    Then the priority list is shown in place of the hub

  Scenario: A dependency-blocked item's escalation reason names the blocking item
    Given an item blocked on another item's completion
    When I open it with Enter or →
    Then the escalation reason names the specific blocking item

  Scenario: An escalated step's escalation reason names what's being asked
    Given an item whose current step is escalated, needing rework
    When I open it with Enter or →
    Then the escalation reason names what's being asked of the operator

  Scenario: A dependency-blocked item's escalation panel shows a single untagged line
    Given an item blocked on another item's completion
    When I open it with Enter or →
    Then the escalation panel shows no "⚠ needs you" tag and no second line
    And the blocking item's id within the reason is coloured as a link, in the cyan colour

  Scenario: An escalated step's escalation panel shows the tagged two-line treatment
    Given an item whose current step is escalated, needing rework
    When I open it with Enter or →
    Then the escalation panel shows a bold amber tag reading "⚠ needs you" on its own line
    And the reason is shown on a second line below the tag, in the text colour

  Scenario Outline: An item that is not needs-attention shows no escalation reason
    Given an item that is "<status>"
    When I open it with Enter or →
    Then no escalation reason is shown

    Examples:
      | status |
      | active |
      | queued |

  Scenario: Selecting the named blocking item jumps straight to its own hub
    Given an item's hub is open, showing an escalation reason that names a blocking item
    When I select the blocking item and press Enter or →
    Then the blocking item's own hub opens

  Scenario: Returning from a blocking item's hub goes back to the original blocked item's hub, not the list
    Given I jumped from a blocked item's hub to its blocking item's hub, from a particular tab
    When Esc or ← is pressed
    Then the original blocked item's hub reappears, at the tab I was on

  Scenario: Closing the hub returns to the list with the same row selected and the same scroll position
    Given I opened an item's hub from a specific row in the priority list
    When I close it with Esc or ←
    Then the priority list reappears with that row still selected, at the same scroll position

  Scenario: Anything done inside the hub leaves the list's own scroll position untouched
    Given I opened an item's hub and scrolled or navigated within it
    When I close it with Esc or ←
    Then the priority list's scroll position is unaffected by anything done inside the hub

  Scenario: Opening a backlog item lands on the Hierarchy tab, showing only that item
    Given the backlog is showing with a todo item
    When I open it with Enter or →
    Then its hub opens, landing on the Hierarchy tab
    And the hierarchy shows only that item, with no step children

  Scenario: Closing a hub opened from the backlog returns to the backlog at the same position
    Given I opened a backlog item's hub from a specific row in the backlog
    When I close it with Esc or ←
    Then the backlog reappears at the same scroll/selection position

  Scenario: A step reclaimed after the breaker killed its worker shows its real, queued state
    Given an item's step was active when the breaker tripped and killed its worker, and was reclaimed to ready
    When I open it with Enter or →
    Then the header and the hierarchy show the step as queued, not active
