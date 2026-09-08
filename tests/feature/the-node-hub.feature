Feature: The node hub
  Opening any node - item or step - lands on the hub: a fixed header above a
  tab strip that is type-aware, since an item and a step share no tabs. An
  item's strip is Description, Workflow, Artifacts, and Cost; a step's is
  Detail, Workflow, Log, and Cost. Landing follows what the node is: an item
  always lands on Description, whatever its status; a step lands on Log while
  its worker is running, and on Detail otherwise - the Workflow tab is never a
  landing tab for either type, and neither is Cost. The header stays fixed
  while Tab cycles forward through whichever tab strip is on screen, wrapping
  from the last tab back to the first - the hub's own tabs while a hub is
  open, the same gesture the app already uses outside any hub to step between
  Current work, Backlog, and Done. Esc/← is the only way to leave an open hub
  now, always returning to wherever it was opened from; Tab no longer doubles
  as an exit, so leaving a hub and moving to the next top-level view costs two
  keypresses (Esc, then Tab) instead of the single Tab press that used to do
  both. Selecting a row inside the Workflow tab replaces the current hub screen in
  place, rather than pushing a new one on top of it - moving between an item's
  own row and its step rows is lateral movement inside one item's tree, not
  descent. Closing the hub (however many rows were visited via the tree)
  always returns to wherever it was opened from - the priority list or the
  backlog - at the same position, since tree navigation never grows the
  screen stack. Each tab's own content beyond this shared shell is specified
  in its own feature file - Description, Workflow, Detail, Log, Artifacts, and
  Cost alike.

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

  Scenario: The header's identity line shows the item's id, project, and title
    Given an item with a project and a workflow, its hub open
    Then the header's identity line shows its id, its project, and its title

  Scenario: A step's own hub identity line shows its item's title, with the step's own id
    Given a step of an item with a project and a workflow, its hub open
    Then the header's identity line shows the step's id, the item's project, and the item's title

  Scenario: The header's stat line names the item's current step and its step count
    Given an item at step "write-code", its hub open
    Then the header's stat line reads "write-code · 1 step"

  Scenario: The header's stat line shows the current step's declared display phrase alongside its stage name
    Given an item at step "code-await-merge" whose workflow declares the display phrase "Review the PR" for that stage, its hub open
    Then the header's stat line reads "Review the PR · code-await-merge · 1 step"

  Scenario: An active item's header shows its wall time with its active time alongside it
    Given an active item at step "build" claimed 14 minutes ago, its hub open
    Then the header's stat line reads "build · 1 step · 14m (0s active)"

  Scenario: A human gate with no worker shows a waiting time, not an elapsed time
    Given a human step with no worker, created 12 minutes ago, its hub open
    Then the header's stat line reads "await-merge · waiting 12m"

  Scenario Outline: A selected step's identity line names its item's title, not its own stored composite title
    Given a step whose stored title is its stage concatenated onto its item's title, whose workflow declares the display phrase "Review the PR" for that stage
    When <key> is pressed
    Then the header's identity line shows the item's title, not the step's stored composite title

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: The header's context line renders in the dim colour
    Given <given>
    Then the header's context line is shown in the dim colour

    Examples:
      | given                                                                |
      | an active item at step "build" claimed 14 minutes ago, its hub open |

  Scenario: An item's tab strip is Description, Workflow, Artifacts, and Cost, never Detail or Log
    Given an item, its hub open
    Then its tab strip shows exactly "Description", "Workflow", "Artifacts", and "Cost", in that order
    And no "Detail" tab and no "Log" tab is shown

  Scenario: A step's tab strip is Detail, Workflow, Log, and Cost, never Description or Artifacts
    Given a step, its hub open
    Then its tab strip shows exactly "Detail", "Workflow", "Log", and "Cost", in that order
    And no "Description" tab and no "Artifacts" tab is shown

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

  Scenario Outline: Tab cycles forward through an item's four tabs, wrapping back to Description
    Given an item's hub is open, on the "<from>" tab
    When Tab is pressed
    Then the "<to>" tab becomes active

    Examples:
      | from        | to          |
      | Description | Workflow    |
      | Workflow    | Artifacts   |
      | Artifacts   | Cost        |
      | Cost        | Description |

  Scenario Outline: Tab cycles forward through a step's four tabs, wrapping back to Detail
    Given a step's hub is open, on the "<from>" tab
    When Tab is pressed
    Then the "<to>" tab becomes active

    Examples:
      | from     | to       |
      | Detail   | Workflow |
      | Workflow | Log      |
      | Log      | Cost     |
      | Cost     | Detail   |

  Scenario: A dependency-blocked item's escalation reason names the blocking item
    Given an item blocked on another item's completion, its hub open
    Then the escalation reason names the specific blocking item

  Scenario: A dependency-blocked item's escalation panel shows a single untagged line
    Given an item blocked on another item's completion, its hub open
    Then the escalation panel shows no "⚠ needs you" tag and no second line
    And the blocking item's id within the reason is coloured as a link, in the cyan colour

  Scenario: An escalated step's escalation panel shows only the tag, on its own line
    Given an item whose current step is escalated, needing rework, its hub open
    Then the escalation panel shows a bold amber tag reading "⚠ needs you" on its own line
    And the escalation panel has no second line

  Scenario: An escalated step with a recorded reason still shows only the tag
    Given an item whose current step is escalated, needing rework, with a recorded reason, its hub open
    Then the escalation panel shows a bold amber tag reading "⚠ needs you" on its own line
    And the escalation panel has no second line

  Scenario: A parked step's own hub shows only the tag in its escalation panel too
    Given a step parked with a needs and a reason recorded, its hub open
    Then the escalation panel shows a bold amber tag reading "⚠ needs you" on its own line
    And the escalation panel has no second line

  Scenario: An escalated step's escalation panel stays one line however long the recorded reason is
    Given an item whose current step is escalated, with a reason far longer than the panel's line cap, its hub open
    Then the escalation panel shows a bold amber tag reading "⚠ needs you" on its own line
    And the escalation panel has no second line
    And the escalation panel shows no truncation ellipsis

  Scenario Outline: An item that is not needs-attention shows no escalation reason
    Given an item that is "<status>", its hub open
    Then no escalation reason is shown

    Examples:
      | status |
      | active |
      | queued |

  Scenario: The description pane is focused on landing, even when the escalation panel is shown
    Given an item blocked on another item's completion, its hub open
    Then the description pane has focus, not the escalation panel

  Scenario: Cycling into the Workflow tab still focuses the table, not the escalation panel
    Given an item whose current step is escalated, needing rework, its hub open
    When Tab is pressed
    Then the hierarchy table has focus, not the escalation panel

  Scenario: Down moves the hierarchy selection when the escalation panel is shown
    Given an item blocked on another item's completion, with a step of its own, its hub open
    And I cycle to the "Workflow" tab
    When Down is pressed
    Then the selection has moved to the next node

  Scenario: Enter opens the highlighted row, not the escalation's blocker, when the escalation panel is shown
    Given an item blocked on another item's completion, with a step of its own, its hub open
    And I cycle to the "Workflow" tab
    When Down is pressed
    And Enter is pressed
    Then that step's own hub opens, not the blocking item's

  Scenario: Confirming the hub's own row in the Workflow tab does nothing, even when the hierarchy has other rows
    Given an item blocked on another item's completion, with a step of its own, its hub open
    And I cycle to the "Workflow" tab
    When Enter is pressed
    Then the screen stack still has depth 2, unchanged by the confirm

  Scenario Outline: Confirming the hub's own row in the Workflow tab does nothing
    Given the backlog is showing with a todo item
    When <key> is pressed
    And I cycle to the "Workflow" tab
    And Enter is pressed
    Then the screen stack still has depth 2, unchanged by the confirm

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: Closing the hub returns to the list with the same row selected and the same scroll position
    Given I opened an item's hub from a specific row in the priority list, with content on every tab
    And I cycle to the "<tab>" tab
    When <key> is pressed
    Then the priority list reappears with that row still selected, at the same scroll position

    Examples:
      | tab    | key |
      | Detail | Esc |
      | Detail | ←   |
      | Log    | Esc |
      | Log    | ←   |
      | Cost   | Esc |
      | Cost   | ←   |

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

  Scenario Outline: A backlog item's Workflow tab shows only that item, with no step children
    Given the backlog is showing with a todo item
    When <key> is pressed
    And I cycle to the "Workflow" tab
    Then the hierarchy shows only that item, with no step children

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: Closing a hub opened from the backlog returns to the backlog at the same position
    Given I opened a backlog item's hub from a specific row in the backlog, with content on every tab
    And I cycle to the "<tab>" tab
    When <key> is pressed
    Then the backlog reappears at the same scroll/selection position

    Examples:
      | tab         | key |
      | Workflow    | Esc |
      | Workflow    | ←   |
      | Artifacts   | Esc |
      | Artifacts   | ←   |
      | Description | Esc |
      | Description | ←   |
      | Cost        | Esc |
      | Cost        | ←   |

  Scenario: A step reclaimed after the breaker killed its worker shows its real, queued state
    Given an item's step was active when the breaker tripped and killed its worker, and was reclaimed to ready, its hub open
    Then the header and the hierarchy show the step as queued, not active
