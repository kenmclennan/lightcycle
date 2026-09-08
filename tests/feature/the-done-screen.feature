Feature: The done screen

  The done tab is the third top-level screen, reached from the backlog by Tab
  or the tab strip (priority list -> backlog -> done -> priority list). It
  lists closed items - a lookup for "did X land?", not a report - newest
  closed first, with the same row grid the backlog already uses and its own
  independent text filter and project picker. Abandoned work is included,
  undistinguished from delivered work. Opening a done item goes straight to
  that item's own hub, the same way opening a backlog item does.

  Scenario: Closed items are listed once the done tab is shown
    Given the store has a closed item
    When I switch to the done tab
    Then the closed item is listed as a row

  Scenario: An item that is still open does not appear in the done tab
    Given the store has an open item and a closed item
    When I switch to the done tab
    Then only the closed item is listed

  Scenario: Closed items are listed newest-closed first
    Given the store has two items, closed in this order: "first closed", then "second closed"
    When I switch to the done tab
    Then the rows appear in the order "second closed", "first closed"

  Scenario: An overall-empty done tab shows a calm message instead of a blank area
    Given the store has no closed items anywhere
    When I switch to the done tab
    Then the message "Nothing is done yet." is shown in place of the list

  Scenario: A done tab filtered to a project with no items shows a message naming the filtered project
    Given the store has closed items, all belonging to a project other than "lightcycle"
    When the done tab is filtered to "lightcycle"
    Then the message "No done items for lightcycle." is shown, with "lightcycle" in the text colour and the rest of the message in the dim colour
    And the hint "Press f to check All." is shown below the message

  Scenario: The done search value and the done project value start in the same column
    Given the done tab is shown with a closed item
    Then the done search value and the done project value start at the same column

  Scenario: Pressing f opens the project filter picker on the done tab
    Given the done tab is shown with the registered projects "org-a/proj-a" and "org-b/proj-b", each with a closed item
    When f is pressed
    Then the picker's header reads "Filter by project"
    And the picker shows "All" with the total item count
    And the picker shows "proj-a" with its own item count

  Scenario: Selecting a project and pressing Enter filters the done tab to it immediately and closes the picker
    Given the done tab is shown with the registered projects "org-a/proj-a" and "org-b/proj-b", each with a closed item
    When f is pressed
    And Down is pressed
    And Enter is pressed
    Then the picker is closed
    And the done tab is filtered to "proj-a"

  Scenario: A typed search term composes with an already-picked project to their intersection
    Given the done tab is shown with the registered projects "org-a/proj-a" and "org-b/proj-b", each with a closed item titled "shared name"
    When f is pressed
    And Down is pressed
    And Enter is pressed
    And / is pressed
    And "shared" is typed into the done search box
    Then only the done row under "proj-a" is shown

  Scenario: Pressing / focuses the done search box
    Given the done tab is shown with a closed item
    When / is pressed
    Then the done search box has focus

  Scenario: Focusing the done search box shifts its label to the cyan colour, and Esc reverts it
    Given the done tab is shown with a closed item
    When / is pressed
    Then the done search label is shown in the cyan colour
    When Esc is pressed
    Then the done search label is not shown in the cyan colour

  Scenario: Esc from the done search box returns focus to the table, leaving the typed term and the filtered results unchanged
    Given the done tab is shown with the closed items "widget one" and "gadget two"
    When / is pressed
    And "widget" is typed into the done search box
    And Esc is pressed
    Then the done table has focus
    And only the done row matching "widget" is still shown

  Scenario: Down from the done search box moves focus to the table, leaving the typed term and the filtered results unchanged
    Given the done tab is shown with the closed items "widget one" and "gadget two"
    When / is pressed
    And "widget" is typed into the done search box
    And Down is pressed
    Then the done table has focus
    And only the done row matching "widget" is still shown

  Scenario: Up from the done search box moves focus to the table, leaving the typed term and the filtered results unchanged
    Given the done tab is shown with the closed items "widget one" and "gadget two"
    When / is pressed
    And "widget" is typed into the done search box
    And Up is pressed
    Then the done table has focus
    And only the done row matching "widget" is still shown

  Scenario: Enter from the done search box opens the narrowed result's own hub
    Given the done tab is shown with the closed items "widget one" and "gadget two"
    When / is pressed
    And "widget" is typed into the done search box
    And Enter is pressed
    Then its hub opens for the done item matching "widget"

  Scenario Outline: Each shortcut for the done tab with the search box focused and rows present appears in the footer, in order
    Given the done tab is shown with a closed item
    When / is pressed
    And the shortcut at position <position> in the footer's shortcut line is read
    Then its key is "<key>"
    And its action is "<action>"

    Examples:
      | position | key   | action       |
      | 1        | ↑↓    | move         |
      | 2        | enter | open         |
      | 3        | esc   | back         |
      | 4        | [/]   | switch tab   |
      | 5        | tab   | current work |
      | 6        | q     | quit         |

  Scenario Outline: Each shortcut for the done tab with the search box focused and zero filtered rows appears in the footer, in order
    Given the done tab is shown with a closed item
    When / is pressed
    And "nonexistent" is typed into the done search box
    And the shortcut at position <position> in the footer's shortcut line is read
    Then its key is "<key>"
    And its action is "<action>"

    Examples:
      | position | key | action       |
      | 1        | esc | back         |
      | 2        | [/] | switch tab   |
      | 3        | tab | current work |
      | 4        | q   | quit         |

  Scenario: The focused-search shortcut strip is actually painted in the footer
    Given the done tab is shown with a closed item
    When / is pressed
    Then the footer's composited frame shows each search-focused shortcut, in order

  Scenario Outline: Opening a done item lands on that item's own hub
    Given the done tab is shown with a closed item
    When <key> is pressed
    Then its hub opens for the closed item

    Examples:
      | key   |
      | Enter |
      | →     |
