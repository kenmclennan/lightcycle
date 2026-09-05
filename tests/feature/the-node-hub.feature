Feature: The node hub
  Opening any node - item or step - lands on the hub: a fixed header above a
  tab strip that is type-aware, since an item and a step share no tabs. An
  item's strip is Description, Hierarchy, and Artifacts; a step's is Detail
  and Log. Landing follows what the node is: an item always lands on
  Description, whatever its status; a step lands on Log while its worker is
  running, and on Detail otherwise. The header stays fixed while ] and [
  cycle the tabs within whichever strip the type has; Tab keeps its own
  global meaning, jumping straight to the backlog (or back to current work)
  from any tab, at any depth, without first backing out through Esc. Closing
  the hub always returns to wherever it was opened from - the priority list
  or the backlog - at the same position. From a step's hub, i opens its
  owning item's hub on top, landing on Description; Esc or ← returns to the
  step's hub beneath it, the same push-on-top/pop-back mechanism used to jump
  to a blocking item. Pressing i on an item's own hub does nothing, since an
  item is already its own owning item. Each tab's own content beyond this
  shared shell is specified in its own feature file - Description,
  Hierarchy, Detail, Log, and Artifacts alike.

  Scenario Outline: Confirming a selected row opens the step it reports, not the item
    Given the priority list is showing with an item
    When I select that item's row
    And <key> is pressed
    Then the step's own hub opens, replacing the list on screen
    And it lands on the "Log" tab

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: Confirming a needs-attention row opens the step's Detail tab, not the item
    Given the priority list is showing with a needs-attention step
    When I select that step's row
    And Enter is pressed
    Then the step's own hub opens, landing on the "Detail" tab

  Scenario: Confirming a queued row opens the step's Detail tab, not the item
    Given the priority list is showing with a queued step
    When I select that step's row
    And Enter is pressed
    Then the step's own hub opens, landing on the "Detail" tab

  Scenario: The header shows the item's identity
    Given an item with a project and a workflow, its hub open
    Then the header shows its id, its title, its project, and its workflow

  Scenario: An item with no workflow shows no workflow line
    Given an item with no workflow, its hub open
    Then no workflow line is shown in the header

  Scenario: The header names the current step
    Given an item at step "write-code", its hub open
    Then the header names "write-code" as the current step

  Scenario: The header shows the current step's declared display phrase alongside its stage name
    Given an item at step "code-await-merge" whose workflow declares the display phrase "Review the PR" for that stage, its hub open
    Then the header names "Review the PR · code-await-merge" as the current step

  Scenario: The header shows the role performing the current step
    Given an item at step "write-code" performed by the role "write-code", its hub open
    Then the header shows "write-code" as the role

  Scenario: An active item's header shows its elapsed time, matching the list's own format
    Given an active item at step "build" claimed 14 minutes ago, its hub open
    Then the header's elapsed time reads "14m"

  Scenario: A human step with no worker shows no role and no elapsed time
    Given an item at a human step, with no worker, its hub open
    Then no role is shown in the header
    And no elapsed time is shown in the header

  Scenario Outline: A selected step's header shows its role and state, not its workflow
    Given a step is selected, rather than an item
    When <key> is pressed
    Then the header shows its role and its state
    And no workflow field is shown

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: An item fieldset field's key stays dim while its value renders at full text brightness
    Given <given>
    Then the header's "<key>" key is shown in the dim colour
    And the header's "<key>" value is shown in the text colour

    Examples:
      | given                                                                             | key     |
      | an item at step "write-code", its hub open                                        | STEP    |
      | an item at step "write-code" performed by the role "write-code", its hub open      | ROLE    |
      | an active item at step "build" claimed 14 minutes ago, its hub open                | ELAPSED |

  Scenario Outline: A fieldset field's key stays dim while its value renders at full text brightness
    Given <given>
    When <trigger> is pressed
    Then the header's "<key>" key is shown in the dim colour
    And the header's "<key>" value is shown in the text colour

    Examples:
      | given                                     | key   | trigger |
      | a step is selected, rather than an item   | STATE | Enter   |
      | a step is selected, rather than an item   | STATE | →       |

  Scenario: An item's tab strip is Description, Hierarchy, and Artifacts, never Detail or Log
    Given an item, its hub open
    Then its tab strip shows exactly "Description", "Hierarchy", and "Artifacts", in that order
    And no "Detail" tab and no "Log" tab is shown

  Scenario: A step's tab strip is Detail and Log, never Description, Hierarchy, or Artifacts
    Given a step, its hub open
    Then its tab strip shows exactly "Detail" and "Log", in that order
    And no "Description" tab, no "Hierarchy" tab, and no "Artifacts" tab is shown

  Scenario Outline: An item's hub lands on the Description tab, whatever its status
    Given an item with the status "<status>", its hub open
    Then it lands on the Description tab

    Examples:
      | status                                |
      | active                                |
      | needs-attention on a human step       |
      | blocked on another item's completion  |
      | queued, not yet run                   |
      | done                                  |

  Scenario Outline: A step's hub lands on Log while its worker runs, and on Detail otherwise
    Given a step with the status "<status>", its hub open
    Then it lands on the "<tab>" tab

    Examples:
      | status                                | tab    |
      | active                                | Log    |
      | needs-attention, a human step         | Detail |
      | blocked on another item's completion  | Detail |
      | queued, not yet run                   | Detail |
      | done                                  | Detail |

  Scenario Outline: ] cycles forward through an item's three tabs, wrapping back to Description
    Given an item's hub is open, on the "<from>" tab
    When ] is pressed
    Then the "<to>" tab becomes active

    Examples:
      | from        | to          |
      | Description | Hierarchy   |
      | Hierarchy   | Artifacts   |
      | Artifacts   | Description |

  Scenario Outline: [ cycles backward through an item's three tabs, in reverse
    Given an item's hub is open, on the "<from>" tab
    When [ is pressed
    Then the "<to>" tab becomes active

    Examples:
      | from        | to          |
      | Description | Artifacts   |
      | Artifacts   | Hierarchy   |
      | Hierarchy   | Description |

  Scenario Outline: ] cycles forward through a step's two tabs, wrapping straight back
    Given a step's hub is open, on the "<from>" tab
    When ] is pressed
    Then the "<to>" tab becomes active

    Examples:
      | from   | to     |
      | Detail | Log    |
      | Log    | Detail |

  Scenario Outline: [ cycles backward through a step's two tabs, the same as forward since there are only two
    Given a step's hub is open, on the "<from>" tab
    When [ is pressed
    Then the "<to>" tab becomes active

    Examples:
      | from   | to     |
      | Detail | Log    |
      | Log    | Detail |

  Scenario Outline: Tab jumps straight to the backlog from any tab in an open item's hub, without cycling tabs
    Given an item, its hub open
    When the "<tab>" tab is active
    And Tab is pressed
    Then the backlog is shown in place of the hub

    Examples:
      | tab         |
      | Hierarchy   |
      | Artifacts   |
      | Description |

  Scenario Outline: Tab jumps straight to the backlog from any tab in an open step's hub, without cycling tabs
    Given a step is selected, rather than an item
    When the "<tab>" tab is active
    And Tab is pressed
    Then the backlog is shown in place of the hub

    Examples:
      | tab    |
      | Detail |
      | Log    |

  Scenario Outline: Tab jumps straight back to current work from any tab in an open item's hub, without cycling tabs
    Given the backlog is showing with a todo item
    When <key> is pressed
    And the "<tab>" tab is active
    And Tab is pressed
    Then the priority list is shown in place of the hub

    Examples:
      | tab         | key   |
      | Hierarchy   | Enter |
      | Hierarchy   | →     |
      | Artifacts   | Enter |
      | Artifacts   | →     |
      | Description | Enter |
      | Description | →     |

  Scenario: A dependency-blocked item's escalation reason names the blocking item
    Given an item blocked on another item's completion, its hub open
    Then the escalation reason names the specific blocking item

  Scenario: An escalated step's escalation reason names what's being asked
    Given an item whose current step is escalated, needing rework, its hub open
    Then the escalation reason names what's being asked of the operator

  Scenario: A dependency-blocked item's escalation panel shows a single untagged line
    Given an item blocked on another item's completion, its hub open
    Then the escalation panel shows no "⚠ needs you" tag and no second line
    And the blocking item's id within the reason is coloured as a link, in the cyan colour

  Scenario: An escalated step's escalation panel shows the tag on its own line, above the reason
    Given an item whose current step is escalated, needing rework, its hub open
    Then the escalation panel shows a bold amber tag reading "⚠ needs you" on its own line
    And the reason is shown on a second line below the tag, in the text colour

  Scenario: An escalated step's escalation panel names no resume command, since resuming is a keypress on Detail now
    Given an item whose current step is escalated, needing rework, its hub open
    Then the escalation panel shows no resume command
    And the escalation panel has no third line

  Scenario: An escalated step with a recorded reason shows it on the third line, with no resume command alongside it
    Given an item whose current step is escalated, needing rework, with a recorded reason, its hub open
    Then the escalation panel's third line names the recorded reason
    And the escalation panel shows no resume command

  Scenario: An escalated step's long reason wraps across multiple lines with every word intact
    Given an item whose current step is escalated, with a reason long enough to wrap, its hub open
    Then the escalation panel shows the reason's final words
    And the escalation panel shows no truncation ellipsis

  Scenario: An escalated step's reason far longer than the cap is truncated with an explicit ellipsis
    Given an item whose current step is escalated, with a reason far longer than the panel's line cap, its hub open
    Then the escalation panel is capped at the configured line count
    And the escalation panel's last line ends with an ellipsis
    And text past the cut point does not appear anywhere in the escalation panel

  Scenario: The escalation panel reflows its wrap when the terminal is resized
    Given an item whose current step is escalated, with a reason that wraps differently at two widths, its hub open
    When the terminal is resized narrower
    Then the escalation panel's rendered lines match the new width, not the original

  Scenario Outline: An item that is not needs-attention shows no escalation reason
    Given an item that is "<status>", its hub open
    Then no escalation reason is shown

    Examples:
      | status |
      | active |
      | queued |

  Scenario: b jumps straight to the escalation's named blocking item's own hub
    Given an item's hub is open, showing an escalation reason that names a blocking item
    When b is pressed
    Then the blocking item's own hub opens

  Scenario: Following the blocker link shows the blocking item's own brief, not a teleport into its running step
    Given an item's hub is open, showing an escalation reason that names a blocking item whose own current step is active
    When b is pressed
    Then the blocking item's own hub opens, landing on the Description tab
    And it is not redirected into its running step

  Scenario: b does nothing when the escalation has no blocker to name
    Given an item whose current step is escalated, needing rework, its hub open
    When b is pressed
    Then nothing happens, since there is no blocker to jump to

  Scenario: The description pane is focused on landing, even when the escalation panel is shown
    Given an item blocked on another item's completion, its hub open
    Then the description pane has focus, not the escalation panel

  Scenario: Cycling into the Hierarchy tab still focuses the table, not the escalation panel
    Given an item whose current step is escalated, needing rework, its hub open
    When ] is pressed
    Then the hierarchy table has focus, not the escalation panel

  Scenario: Down moves the hierarchy selection when the escalation panel is shown
    Given an item blocked on another item's completion, with a step of its own, its hub open
    And I cycle to the "Hierarchy" tab with ]
    When Down is pressed
    Then the selection has moved to the next node

  Scenario: Enter opens the highlighted row, not the escalation's blocker, when the escalation panel is shown
    Given an item blocked on another item's completion, with a step of its own, its hub open
    And I cycle to the "Hierarchy" tab with ]
    When Down is pressed
    And Enter is pressed
    Then that step's own hub opens, not the blocking item's

  Scenario: Confirming the hub's own row in the Hierarchy tab does nothing, even when the hierarchy has other rows
    Given an item blocked on another item's completion, with a step of its own, its hub open
    And I cycle to the "Hierarchy" tab with ]
    When Enter is pressed
    Then the screen stack still has depth 2, unchanged by the confirm

  Scenario Outline: Confirming the hub's own row in the Hierarchy tab does nothing
    Given the backlog is showing with a todo item
    When <key> is pressed
    And I cycle to the "Hierarchy" tab with ]
    And Enter is pressed
    Then the screen stack still has depth 2, unchanged by the confirm

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: Pressing i on a step's hub opens its owning item's hub, on top of the step's
    Given a step, its hub open
    When i is pressed
    Then the item's own hub opens, on top of the step's, landing on the Description tab

  Scenario Outline: Returning from a step's owning-item hub goes back to the step's hub, not the list
    Given a step, its hub open
    And i is pressed
    When <key> is pressed
    Then the step's own hub reappears

    Examples:
      | key |
      | Esc |
      | ←   |

  Scenario: Pressing i on an item's own hub does nothing
    Given an item, its hub open
    When i is pressed
    Then the screen stack still has depth 2, unchanged by the keypress

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
      | tab    | key |
      | Detail | Esc |
      | Detail | ←   |
      | Log    | Esc |
      | Log    | ←   |

  Scenario Outline: Anything done inside the hub leaves the list's own scroll position untouched
    Given I opened an item's hub and scrolled or navigated within it
    When <key> is pressed
    Then the priority list's scroll position is unaffected by anything done inside the hub

    Examples:
      | key |
      | Esc |
      | ←   |

  Scenario Outline: Opening a backlog item lands on the Description tab
    Given the backlog is showing with a todo item
    When <key> is pressed
    Then its hub opens, landing on the Description tab

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: A backlog item's Hierarchy tab shows only that item, with no step children
    Given the backlog is showing with a todo item
    When <key> is pressed
    And I cycle to the "Hierarchy" tab with ]
    Then the hierarchy shows only that item, with no step children

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
      | Artifacts   | Esc |
      | Artifacts   | ←   |
      | Description | Esc |
      | Description | ←   |

  Scenario: A step reclaimed after the breaker killed its worker shows its real, queued state
    Given an item's step was active when the breaker tripped and killed its worker, and was reclaimed to ready, its hub open
    Then the header and the hierarchy show the step as queued, not active
