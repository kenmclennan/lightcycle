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

  Scenario Outline: The header shows the item's identity
    Given an item with a project, a theme, and a workflow
    When <key> is pressed
    Then the header shows its id, its title, its project, its theme, and its workflow

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: An item with no theme shows no theme line
    Given an item with no theme
    When <key> is pressed
    Then no theme line is shown in the header

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: An item with no workflow shows no workflow line
    Given an item with no workflow
    When <key> is pressed
    Then no workflow line is shown in the header

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: The header names the current step
    Given an item at step "write-code"
    When <key> is pressed
    Then the header names "write-code" as the current step

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: The header shows the current step's declared display phrase alongside its stage name
    Given an item at step "code-await-merge" whose workflow declares the display phrase "Review the PR" for that stage
    When <key> is pressed
    Then the header names "Review the PR · code-await-merge" as the current step

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: The header shows the role performing the current step
    Given an item at step "write-code" performed by the role "write-code"
    When <key> is pressed
    Then the header shows "write-code" as the role

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: An active item's header shows its elapsed time, matching the list's own format
    Given an active item at step "build" claimed 14 minutes ago
    When <key> is pressed
    Then the header's elapsed time reads "14m"

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: A human step with no worker shows no role and no elapsed time
    Given an item at a human step, with no worker
    When <key> is pressed
    Then no role is shown in the header
    And no elapsed time is shown in the header

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: A selected step's header shows its role and state, not theme or workflow
    Given a step is selected, rather than an item or theme
    When <key> is pressed
    Then the header shows its role and its state
    And no theme or workflow fields are shown

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: A fieldset field's key stays dim while its value renders at full text brightness
    Given <given>
    When <trigger> is pressed
    Then the header's "<key>" key is shown in the dim colour
    And the header's "<key>" value is shown in the text colour

    Examples:
      | given                                                              | key     | trigger |
      | an item at step "write-code"                                       | STEP    | Enter   |
      | an item at step "write-code"                                       | STEP    | →       |
      | an item at step "write-code" performed by the role "write-code"    | ROLE    | Enter   |
      | an item at step "write-code" performed by the role "write-code"    | ROLE    | →       |
      | an active item at step "build" claimed 14 minutes ago              | ELAPSED | Enter   |
      | an active item at step "build" claimed 14 minutes ago              | ELAPSED | →       |
      | a step is selected, rather than an item or theme                   | STATE   | Enter   |
      | a step is selected, rather than an item or theme                   | STATE   | →       |

  Scenario: A theme's header is its id, its title, and its item count - nothing else
    Given a theme with 4 items underneath, its hub open
    Then the header shows "theme · 4 items underneath"
    And no project, theme, or workflow line is shown in the header

  Scenario: A theme's header shows no project line, even when its items belong to different projects
    Given a theme whose items belong to different projects, its hub open
    Then no project line is shown in the header

  Scenario Outline: Opening a node lands on the tab that matches its status
    Given a node with the status "<status>", its hub open
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
    When <key> is pressed
    And the "<tab>" tab is active
    And Tab is pressed
    Then the backlog is shown in place of the hub

    Examples:
      | tab         | key   |
      | Hierarchy   | Enter |
      | Hierarchy   | →     |
      | Log         | Enter |
      | Log         | →     |
      | Artifacts   | Enter |
      | Artifacts   | →     |
      | Description | Enter |
      | Description | →     |

  Scenario Outline: Tab jumps straight back to current work from a node opened out of the backlog
    Given the backlog is showing with a todo item
    When <key> is pressed
    And Tab is pressed
    Then the priority list is shown in place of the hub

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: A dependency-blocked item's escalation reason names the blocking item
    Given an item blocked on another item's completion, its hub open
    Then the escalation reason names the specific blocking item

  Scenario Outline: An escalated step's escalation reason names what's being asked
    Given an item whose current step is escalated, needing rework
    When <key> is pressed
    Then the escalation reason names what's being asked of the operator

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: A dependency-blocked item's escalation panel shows a single untagged line
    Given an item blocked on another item's completion, its hub open
    Then the escalation panel shows no "⚠ needs you" tag and no second line
    And the blocking item's id within the reason is coloured as a link, in the cyan colour

  Scenario Outline: An escalated step's escalation panel shows the tag on its own line, above the reason
    Given an item whose current step is escalated, needing rework
    When <key> is pressed
    Then the escalation panel shows a bold amber tag reading "⚠ needs you" on its own line
    And the reason is shown on a second line below the tag, in the text colour

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: An escalated step's escalation panel names the resume command on its third line
    Given an item whose current step is escalated, needing rework
    When <key> is pressed
    Then the escalation panel's third line names the resume command

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: An escalated step with a recorded reason shows it alongside the resume command
    Given an item whose current step is escalated, needing rework, with a recorded reason
    When <key> is pressed
    Then the escalation panel's third line names the resume command
    And the escalation panel's third line also names the recorded reason

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: An escalated step's long reason wraps across multiple lines with every word intact
    Given an item whose current step is escalated, with a reason long enough to wrap
    When Enter is pressed
    Then the escalation panel shows the reason's final words
    And the escalation panel shows no truncation ellipsis

  Scenario: An escalated step's reason far longer than the cap is truncated with an explicit ellipsis
    Given an item whose current step is escalated, with a reason far longer than the panel's line cap
    When Enter is pressed
    Then the escalation panel is capped at the configured line count
    And the escalation panel's last line ends with an ellipsis
    And text past the cut point does not appear anywhere in the escalation panel

  Scenario: The escalation panel reflows its wrap when the terminal is resized
    Given an item whose current step is escalated, with a reason that wraps differently at two widths
    When Enter is pressed
    And the terminal is resized narrower
    Then the escalation panel's rendered lines match the new width, not the original

  Scenario Outline: An item that is not needs-attention shows no escalation reason
    Given an item that is "<status>"
    When <key> is pressed
    Then no escalation reason is shown

    Examples:
      | status | key   |
      | active | Enter |
      | active | →     |
      | queued | Enter |
      | queued | →     |

  Scenario: b jumps straight to the escalation's named blocking item's own hub
    Given an item's hub is open, showing an escalation reason that names a blocking item
    When b is pressed
    Then the blocking item's own hub opens

  Scenario Outline: b does nothing when the escalation has no blocker to name
    Given an item whose current step is escalated, needing rework
    When <key> is pressed
    And b is pressed
    Then nothing happens, since there is no blocker to jump to

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: The hierarchy table is focused on landing, even when the escalation panel is shown
    Given an item blocked on another item's completion, its hub open
    Then the hierarchy table has focus, not the escalation panel

  Scenario Outline: Cycling into the Hierarchy tab still focuses the table, not the escalation panel
    Given an item whose current step is escalated, needing rework
    When <key> is pressed
    And ] is pressed
    And ] is pressed
    Then the hierarchy table has focus, not the escalation panel

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: Down moves the hierarchy selection when the escalation panel is shown
    Given an item blocked on another item's completion, with a step of its own, its hub open
    When Down is pressed
    Then the selection has moved to the next node

  Scenario: Enter opens the highlighted row, not the escalation's blocker, when the escalation panel is shown
    Given an item blocked on another item's completion, with a step of its own, its hub open
    When Down is pressed
    And Enter is pressed
    Then that step's own hub opens, not the blocking item's

  Scenario: Confirming the hub's own row in the Hierarchy tab does nothing, even when the hierarchy has other rows
    Given an item blocked on another item's completion, with a step of its own, its hub open
    When Enter is pressed
    Then the screen stack still has depth 2, unchanged by the confirm

  Scenario Outline: Confirming the hub's own row in the Hierarchy tab does nothing
    Given the backlog is showing with a todo item
    When <key> is pressed
    And Enter is pressed
    Then the screen stack still has depth 2, unchanged by the confirm

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: Returning from a blocking item's hub goes back to the original blocked item's hub, not the list
    Given a blocked item's hub is open, with content on every tab
    And I cycle to the "<tab>" tab with ]
    And I jump to its blocking item's hub
    When <key> is pressed
    Then the original blocked item's hub reappears, at the tab I was on

    Examples:
      | tab         | key |
      | Hierarchy   | Esc |
      | Hierarchy   | ←   |
      | Log         | Esc |
      | Log         | ←   |
      | Artifacts   | Esc |
      | Artifacts   | ←   |
      | Description | Esc |
      | Description | ←   |

  Scenario Outline: Closing the hub returns to the list with the same row selected and the same scroll position
    Given I opened an item's hub from a specific row in the priority list, with content on every tab
    And I cycle to the "<tab>" tab with ]
    When <key> is pressed
    Then the priority list reappears with that row still selected, at the same scroll position

    Examples:
      | tab         | key |
      | Hierarchy   | Esc |
      | Hierarchy   | ←   |
      | Log         | Esc |
      | Log         | ←   |
      | Artifacts   | Esc |
      | Artifacts   | ←   |
      | Description | Esc |
      | Description | ←   |

  Scenario Outline: Anything done inside the hub leaves the list's own scroll position untouched
    Given I opened an item's hub and scrolled or navigated within it
    When <key> is pressed
    Then the priority list's scroll position is unaffected by anything done inside the hub

    Examples:
      | key |
      | Esc |
      | ←   |

  Scenario Outline: Opening a backlog item lands on the Hierarchy tab, showing only that item
    Given the backlog is showing with a todo item
    When <key> is pressed
    Then its hub opens, landing on the Hierarchy tab
    And the hierarchy shows only that item, with no step children

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: Closing a hub opened from the backlog returns to the backlog at the same position
    Given I opened a backlog item's hub from a specific row in the backlog, with content on every tab
    And I cycle to the "<tab>" tab with ]
    When <key> is pressed
    Then the backlog reappears at the same scroll/selection position

    Examples:
      | tab         | key |
      | Hierarchy   | Esc |
      | Hierarchy   | ←   |
      | Log         | Esc |
      | Log         | ←   |
      | Artifacts   | Esc |
      | Artifacts   | ←   |
      | Description | Esc |
      | Description | ←   |

  Scenario Outline: A step reclaimed after the breaker killed its worker shows its real, queued state
    Given an item's step was active when the breaker tripped and killed its worker, and was reclaimed to ready
    When <key> is pressed
    Then the header and the hierarchy show the step as queued, not active

    Examples:
      | key   |
      | Enter |
      | →     |
