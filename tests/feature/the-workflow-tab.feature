Feature: The workflow tab
  The Workflow tab renders a node's whole tree, from its item down, always
  fully expanded, never collapsed. Every row shows its own real id, its
  current state in the same icon/colour vocabulary as the priority list. A
  done or queued step whose role is human draws a hollow square in place of
  the ordinary hollow-circle state glyph; a live gate or escalation is
  already distinguishable by its own amber/red glyph, so the square never
  applies there. A step's label also carries its phase, and, whenever its
  item has run more than one pass, its pass number. A step always renders
  one level below its item - never a pass row, never a second level of
  nesting. The node the hub is open for is highlighted wherever it falls;
  as the operator scrolls past its parent item, that item's row stays
  pinned to the top so context is never lost. Arrow keys move the
  selection; Enter or → opens whatever is highlighted into its own hub;
  a and l jump straight to a highlighted node's Artifacts or Log, skipping
  its own contextual default.

  Scenario: An item's hierarchy shows the item itself as the root
    Given an item
    When I open the hierarchy from it or one of its steps
    Then that item is shown as the root, with its steps below, and no row above it

  Scenario: A node's depth is visible by indentation
    Given the hierarchy is showing an item and one of its steps
    When I look at each node
    Then its depth - item or step - is visible by indentation

  Scenario: Each node shows its own real id and current state
    Given a node in the hierarchy
    When it renders
    Then its own real id is shown alongside its title
    And its current state is shown using the same icon and colour as the priority list

  Scenario: The active state's icon rests on a diamond and pulses through four frames
    Given the hierarchy is open, showing an active step
    Then the step's icon rests on the black diamond
    When the active-glyph animation ticks four times
    Then the step's icon cycles through the diamond pulse frames and returns to the black diamond

  Scenario: The hierarchy tree's row area shares the frame's own background, not an unnamed default
    Given the hierarchy tab is open
    When it renders
    Then the row area's background matches the same bg colour as the rest of the frame

  Scenario: The hierarchy updates without a manual refresh when a node's state changes
    Given the hierarchy is open, showing a queued step
    When that step is claimed and becomes active
    And one poll interval elapses
    Then the step's row shows the active state, without a manual refresh

  Scenario: A done human step shows the hollow square in place of the done glyph
    Given a human step that is done
    When it renders in the hierarchy
    Then its icon is the hollow square, not the ordinary done glyph

  Scenario: A queued human step blocked on a dependency shows the hollow square in place of the queued glyph
    Given a human step made queued by an unresolved dependency
    When it renders in the hierarchy
    Then its icon is the hollow square, not the ordinary queued glyph

  Scenario: A done agent step and a queued agent step both keep the plain round glyph
    Given a done agent step and a queued agent step, blocked on a dependency
    When they render
    Then both keep the ordinary round glyph, not the hollow square

  Scenario: A step row is labelled by its step name, not its stored title
    Given a step whose stored title is the step name followed by a body
    When it renders in the hierarchy
    Then the step's row label is exactly its step name, with no title body

  Scenario: A step row shows its declared display phrase in place of its raw stage name
    Given a step at stage "code-await-merge" whose workflow declares the display phrase "Review the PR" for that stage
    When it renders in the hierarchy
    Then the step's row label reads "Review the PR", not "code-await-merge"

  Scenario: A step row shows its declared phase name ahead of its display phrase
    Given a step at stage "code-await-merge" whose workflow declares the phase "code" and the display phrase "Review the PR" for that stage
    When it renders in the hierarchy
    Then the step's row label includes "code" ahead of "Review the PR"

  Scenario: A step in an item's first pass shows no pass number in its label
    Given a step in an item's first pass
    When it renders in the hierarchy
    Then the step's row label does not mention a pass number

  Scenario: A step past an item's first pass shows its pass number in its label
    Given a step in an item's second pass
    When it renders in the hierarchy
    Then the step's row label mentions its pass number

  Scenario: A first-pass step also shows its pass number once the item has run a second pass
    Given a step in an item's first pass, and that item has since run a second pass
    When it renders in the hierarchy
    Then the step's row label mentions pass 1

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

  Scenario Outline: When a hierarchy row cannot fit unstacked, the title moves to a continuation line indented by the grid's glyph width plus the row's own depth, spanning the row without wrapping mid-word
    Given a hierarchy row at depth <depth> whose atomic and glyph columns leave less than the flexible minimum for the title, on a terminal <at a width>
    When it renders in the hierarchy
    Then the icon and id remain on the row's first line, each padded to its atomic width, with cost right-aligned
    And the title appears on a continuation line indented 3 characters plus the row's own depth indent of <depth>
    And no fragment of the title's prose is split mid-word

    Examples:
      | depth | at a width                            |
      | 0     | just narrow enough to force stacking  |
      | 0     | just wide enough to clear the floor   |
      | 1     | just narrow enough to force stacking  |
      | 1     | just wide enough to clear the floor   |

  Scenario: A node blocked on a dependency shows a dependency indicator alongside the queued state, not gate or escalation
    Given a step blocked on another item's completion
    When it renders in the hierarchy
    Then a dependency indicator is shown alongside its state
    And that state is the queued glyph, not the gate or escalation glyph

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
    When <key> is pressed
    Then it opens into its own tabbed hub, landing on the tab appropriate to its type and state

    Examples:
      | type  | key   |
      | item  | Enter |
      | item  | →     |
      | step  | Enter |
      | step  | →     |

  Scenario Outline: Leaving a hub reached by selecting a node from the Workflow tab does not restore the tab's prior state
    Given I opened a node from the Workflow tab
    When <key> is pressed
    Then the hub is no longer showing, since selecting a node replaced it rather than adding to it

    Examples:
      | key |
      | Esc |
      | ←   |

  Scenario: A step's own hub shows the same tree as its owning item's, rooted at the item
    Given a step's hub is open directly, not its owning item's
    When I view the Workflow tab
    Then the owning item is the root row
    And the step's own row is present and highlighted

  Scenario: An ancestor scrolled out of view is pinned to the top
    Given the hierarchy is scrolled past a node's parent item
    When that ancestor leaves the visible scroll area
    Then its row stays pinned to the top instead of scrolling away

  Scenario: Scrolling back to an ancestor's own row removes the pinned duplicate
    Given an ancestor's row is pinned to the top because it scrolled out of view
    When I scroll back up to where its actual row is
    Then the pinned duplicate is no longer shown

  Scenario: A pinned ancestor's row shows its own state icon, like every other row
    Given an ancestor's row is pinned to the top because it scrolled out of view
    When it renders
    Then its row shows its own state icon, using the same icon and colour vocabulary as every other row

  Scenario: Pressing a on a highlighted item opens its Artifacts tab directly
    Given an item is highlighted in the hierarchy, not yet opened
    When a is pressed
    Then its Artifacts tab opens directly, skipping its own contextual default

  Scenario: a is a no-op on a highlighted step, since a step has no Artifacts tab
    Given a step is highlighted in the hierarchy, not yet opened
    When a is pressed
    Then nothing happens, since there is no Artifacts tab to open

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

  Scenario: l is a no-op on a highlighted item with a live current step, since an item has no Log tab
    Given an item whose current step is active, highlighted in the hierarchy
    When l is pressed
    Then nothing happens, since there is no Log tab to open

  Scenario: l is a no-op on a highlighted done item, since an item has no Log tab
    Given an item whose every step is done, highlighted in the hierarchy
    When l is pressed
    Then nothing happens, since there is no Log tab to open

  Scenario: A root node with no parent is highlighted at the top row
    Given the current node is a root item
    When I view the Workflow tab
    Then it is highlighted at the top row

  Scenario: A nested node is highlighted at its actual depth
    Given the current node is a step nested under an item
    When I view the Workflow tab
    Then it is highlighted at its actual depth, not the top row

  Scenario: The Workflow tab lands on the current step, not the item, when the item has one already started
    Given an item with one completed step and one queued step after it
    When I view the Workflow tab
    Then the queued step's row is highlighted, not the item's own row

  Scenario: The Workflow tab lands on the current step, not the item, and it is scrolled into view even when it is far below the fold
    Given an item with 40 completed steps and one queued step after them
    When I view the Workflow tab
    Then the queued step's row is highlighted, not the item's own row
    And it is scrolled into view

  Scenario: The Workflow tab still lands on the item's own row when every step is done
    Given an item whose every step is done
    When I view the Workflow tab
    Then it is highlighted at the top row

  Scenario Outline: Confirming the Workflow tab's default selection on an in-progress item opens its current step, not the item itself
    Given an item with one completed step and one queued step after it
    When I view the Workflow tab
    And <key> is pressed
    Then that step's own hub opens

    Examples:
      | key   |
      | Enter |
      | →     |
