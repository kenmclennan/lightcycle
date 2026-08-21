Feature: The hierarchy tab
  The Hierarchy tab renders a node's whole tree, from its actual root down -
  a theme if one exists, otherwise the top-level item itself - always fully
  expanded, never collapsed. Every row shows its own real id, its current
  state in the same icon/colour vocabulary as the priority list, and, for a
  step, the role that performed or is performing it. The node the hub is
  open for is highlighted wherever it falls; as the operator scrolls past
  its parent item or theme, that ancestor's row stays pinned to the top so
  context is never lost. Arrow keys move the selection; Enter or → opens
  whatever is highlighted into its own hub; a and l jump straight to a
  highlighted node's Artifacts or Log, skipping its own contextual default.

  Scenario: A node with a non-internal artifact shows a content indicator
    Given a node with an artifact whose internal flag is false
    When it appears in the hierarchy
    Then it shows a content indicator

  Scenario: A node with only internal-flagged artifacts shows no content indicator
    Given a node with only internal-flagged artifacts
    When it appears in the hierarchy
    Then no content indicator is shown

  Scenario: A node with no artifacts shows no content indicator
    Given a node with no artifacts
    When it appears in the hierarchy
    Then no content indicator is shown

  Scenario: Opening a node with a content indicator reveals a viewable artifact
    Given a node showing a content indicator
    When I open that node
    Then at least one artifact I can actually view is there

  Scenario: A themed node's hierarchy shows its theme at the root
    Given an item under a theme
    When I open the hierarchy from it or one of its steps
    Then the theme is shown at the top, with all its items and their steps below

  Scenario: A themeless item's hierarchy shows the item itself as the root
    Given a themeless item
    When I open the hierarchy from it or one of its steps
    Then that item is shown as the root, with its steps below, and no blank or missing theme row

  Scenario: A node's depth is visible by indentation
    Given the hierarchy is showing a theme, one of its items, and one of that item's steps
    When I look at each node
    Then its depth - theme, item, or step - is visible by indentation

  Scenario: Each node shows its own real id and current state
    Given a node in the hierarchy
    When it renders
    Then its own real id is shown alongside its title
    And its current state is shown using the same icon and colour as the priority list

  Scenario: The hierarchy updates without a manual refresh when a node's state changes
    Given the hierarchy is open, showing a queued step
    When that step is claimed and becomes active
    And one poll interval elapses
    Then the step's row shows the active state, without a manual refresh

  Scenario: A step performed by a worker shows its role alongside its state
    Given a step performed by the role "write-code"
    When it renders in the hierarchy
    Then its role "write-code" is shown alongside its state

  Scenario: A human step shows "human" as its role, not a blank
    Given a step whose role is "human"
    When it renders in the hierarchy
    Then "human" is shown as its role

  Scenario Outline: The id column widens to fit the longest id in the tree, whatever produced it, without truncating or wrapping it
    Given a node in the hierarchy with id "<id>" (<id source>)
    When it renders in the hierarchy
    Then its id is shown in full, on one line

    Examples:
      | id source                                    | id                |
      | this project's own shortcode                 | LC-290.1.86       |
      | the engine's default, unshortened shortcode  | LIGHTCYCLE-3.1.1  |

  Scenario: Two distinct nodes whose ids would collide if truncated render in full and stay distinguishable
    Given an item "LIGHTCYCLE-3.1" and its own step "LIGHTCYCLE-3.1.1" both shown in the hierarchy
    When they render
    Then both ids are shown in full
    And the item's row and the step's row are distinguishable from each other

  Scenario Outline: The role column widens to fit a role name longer than its historical fixed width, without clipping it
    Given a step performed by the role "<role>"
    When it renders in the hierarchy
    Then its role "<role>" is shown in full, on one line

    Examples:
      | role               |
      | implement-features |
      | handle-feedback    |
      | resolve-conflict   |
      | review-conflict    |
      | feature-writer     |

  Scenario: When a hierarchy row cannot fit unstacked, the title moves to a continuation line indented past the row's own depth
    Given a hierarchy row whose atomic and glyph columns leave less than the flexible minimum for the title
    When it renders in the hierarchy
    Then the icon, content indicator, id and role remain on the row's first line, with the role right-aligned
    And the title appears on a continuation line indented to the row's own depth plus 2 characters

  Scenario: A node blocked on a dependency shows a dependency indicator distinct from other blocked reasons
    Given a step blocked on another item's completion
    When it renders in the hierarchy
    Then a dependency indicator is shown alongside its state
    And that indicator is distinct from a step that is blocked for any other reason

  Scenario: Down moves the selection to the next node
    Given the hierarchy has more rows than fit on one screen
    When Down is pressed
    Then the selection has moved to the next node, scrolling as needed

  Scenario: Up moves the selection to the previous node
    Given the hierarchy has more rows than fit on one screen
    And the selection is not on the first node
    When Up is pressed
    Then the selection has moved to the previous node

  Scenario: The selection does not wrap past the last node
    Given the selection is on the last node in the hierarchy
    When Down is pressed
    Then the selection has not moved past the last node

  Scenario: The selection does not wrap past the first node
    Given the selection is on the first node in the hierarchy
    When Up is pressed
    Then the selection has not moved past the first node

  Scenario: Ctrl-D jumps the hierarchy roughly a full screen forward
    Given the hierarchy is longer than one screen
    When Ctrl-D is pressed
    Then the view has jumped forward by roughly a full screen

  Scenario: Ctrl-U jumps the hierarchy roughly a full screen back
    Given the hierarchy is longer than one screen
    When Ctrl-D is pressed
    And Ctrl-U is pressed
    Then the selection is back on the row it started on

  Scenario Outline: Selecting any node type in the hierarchy opens it into its own hub
    Given a "<type>" is highlighted in the hierarchy
    When Enter or → is pressed
    Then it opens into its own tabbed hub, landing on the tab that matches its state

    Examples:
      | type  |
      | theme |
      | item  |
      | step  |

  Scenario: Closing a node opened from the hierarchy returns to the hierarchy tab, same node, same position
    Given I opened a node from the Hierarchy tab
    When I close it with Esc or ←
    Then the Hierarchy tab reappears with that node still selected, scrolled to the same position

  Scenario: An ancestor scrolled out of view is pinned to the top
    Given the hierarchy is scrolled past a node's parent item or theme
    When that ancestor leaves the visible scroll area
    Then its row stays pinned to the top instead of scrolling away

  Scenario: Scrolling back to an ancestor's own row removes the pinned duplicate
    Given an ancestor's row is pinned to the top because it scrolled out of view
    When I scroll back up to where its actual row is
    Then the pinned duplicate is no longer shown

  Scenario: Pressing a on a highlighted node opens its Artifacts tab directly
    Given a node is highlighted in the hierarchy, not yet opened
    When a is pressed
    Then its Artifacts tab opens directly, skipping its own contextual default

  Scenario: Pressing l on a highlighted active node opens its live log directly
    Given an active step is highlighted in the hierarchy
    When l is pressed
    Then its Log tab opens directly, showing the live tail

  Scenario: Pressing l on a highlighted done node opens its past log directly
    Given a done step is highlighted in the hierarchy
    When l is pressed
    Then its Log tab opens directly, showing its past log

  Scenario: l is a no-op on a highlighted human step
    Given a human step is highlighted in the hierarchy
    When l is pressed
    Then nothing happens, since there is no log to show

  Scenario: l is a no-op on a highlighted node that hasn't run yet
    Given a queued step is highlighted in the hierarchy
    When l is pressed
    Then nothing happens, since there is no log to show

  Scenario: A root node with no parent is highlighted at the top row
    Given the current node is a themeless root item
    When I view the Hierarchy tab
    Then it is highlighted at the top row

  Scenario: A nested node is highlighted at its actual depth
    Given the current node is a step nested under an item under a theme
    When I view the Hierarchy tab
    Then it is highlighted at its actual depth, not the top row
