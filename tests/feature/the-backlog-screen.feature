Feature: The backlog screen

  The backlog is the second top-level screen, reached from the Priority List
  by Tab or the tab strip. It lists todo items - items not yet planned or
  active - each with its owning project, and lets the operator narrow it to
  one registered project at a time through a picker opened with f, which
  shows every registered project's own count, zero-count ones included, so
  it stays a constant-time interaction no matter how many projects exist.
  When there is nothing to show, a calm message explains why - distinguishing
  a backlog that is empty everywhere from one that is only empty under the
  active filter - instead of leaving a blank area. Opening a backlog item
  into the node hub, and the Tab jump to this screen from several levels
  deep, are not part of this screen and belong to later work.

  Scenario: Todo items are listed once the backlog is shown
    Given the store has a todo item
    When I switch to the backlog
    Then the todo item is listed as a row

  Scenario: A todo item that is later activated no longer appears in the backlog
    Given the backlog is shown with a todo item
    When that item is activated
    And one poll interval elapses
    Then the item no longer appears in the backlog

  Scenario: Ctrl-D jumps the backlog selection forward by the same amount as Page Down
    Given the backlog is shown with more todo items than fit on one screen
    When Ctrl-D is pressed
    Then the selection has moved forward by the same amount Page Down would move it

  Scenario: Ctrl-U jumps the backlog selection back by the same amount as Page Up
    Given the backlog is shown with more todo items than fit on one screen
    When Ctrl-D is pressed
    And Ctrl-U is pressed
    Then the selection is back on the row it started on

  Scenario: A backlog row for an item tagged to a registered project shows the shortened project label in cyan
    Given the backlog is shown with a todo item whose repo is "kenmclennan/lightcycle" under the registered project "kenmclennan/lightcycle"
    Then that item's row shows "lightcycle" as its project, in the cyan colour

  Scenario Outline: The id column widens to fit the longest id in the backlog, whatever produced it, without truncating or wrapping it
    Given the backlog is shown with a todo item with id "<id>" (<id source>)
    Then that item's row shows "<id>" as its id, in full, on one line

    Examples:
      | id source                                    | id                |
      | this project's own shortcode                 | LC-143.1          |
      | a plain generated id                         | fake-a72427b9     |
      | the engine's default, unshortened shortcode  | LIGHTCYCLE-3.1    |

  Scenario: Two ids that would look identical if truncated both render in full and stay distinguishable
    Given the backlog is shown with two todo items whose ids are "LC-1234.1" and "LC-1234.10"
    Then both ids are shown in full
    And the two rows' ids are distinguishable from each other

  Scenario Outline: When a backlog row cannot fit unstacked, the title moves to a continuation line indented by the grid's glyph width and spanning the row without wrapping mid-word
    Given a backlog row whose atomic and glyph columns leave less than the flexible minimum for the title, on a terminal <at a width>
    Then the cursor, id and project remain on the row's first line, each padded to its atomic width
    And the title appears on a continuation line indented 2 characters - the row's glyph width, not where the title column starts in the unstacked grid
    And no fragment of the title's prose is split mid-word

    Examples:
      | at a width                            |
      | just narrow enough to force stacking  |
      | just wide enough to clear the floor   |

  Scenario: A backlog row for an item with no registered project shows a blank project field
    Given the backlog is shown with a todo item with no registered project
    Then that item's row shows a blank project field

  Scenario: Pressing Tab from the priority list shows the backlog in its place
    Given the dashboard has launched
    When Tab is pressed
    Then the backlog is shown in place of the priority list

  Scenario: Pressing Tab again from the backlog returns to the priority list in its place
    Given the dashboard has launched
    When Tab is pressed
    And Tab is pressed
    Then the priority list is shown in place of the backlog

  Scenario: Pressing f opens the project filter picker listing All and every registered project with its own count
    Given the backlog is shown with the registered projects "org-a/proj-a" and "org-b/proj-b", each with backlogged items
    When f is pressed
    Then the picker's header reads "Filter by project"
    And the picker shows "All" with the total item count
    And the picker shows "proj-a" with its own item count
    And the picker shows "proj-b" with its own item count

  Scenario: The picker includes a registered project with no backlogged items, showing a zero count
    Given the backlog is shown with the registered project "org-c/proj-c" and no backlogged items under it
    When f is pressed
    Then the picker shows "proj-c" with count 0

  Scenario: The picker paints every row's count in full, right-aligned alongside its label, on the actual composited frame
    Given the backlog is shown with the registered project "lightcycle" and 13 todo items in total, 1 of them under "lightcycle"
    When f is pressed
    Then the picker's composited frame shows "All" with its total item count, right-aligned alongside its label
    And the picker's composited frame shows "lightcycle" with its own item count, right-aligned alongside its label

  Scenario: Down moves the picker's highlighted option to the next entry
    Given the backlog is shown with the registered project "org-a/proj-a"
    When f is pressed
    And Down is pressed
    Then the picker's highlighted option is "proj-a"

  Scenario: Up moves the picker's highlighted option back to the previous entry
    Given the backlog is shown with the registered project "org-a/proj-a"
    When f is pressed
    And Down is pressed
    And Up is pressed
    Then the picker's highlighted option is "All"

  Scenario: Selecting a project and pressing Enter filters the backlog to it immediately and closes the picker
    Given the backlog is shown with the registered projects "org-a/proj-a" and "org-b/proj-b", each with backlogged items
    When f is pressed
    And Down is pressed
    And Enter is pressed
    Then the picker is closed
    And the backlog is filtered to "proj-a" without a poll interval elapsing

  Scenario: Pressing Esc closes the picker without changing the filter
    Given the backlog is shown with the registered project "org-a/proj-a"
    When f is pressed
    And Esc is pressed
    Then the picker is closed
    And the backlog is still filtered to "All"

  Scenario: While the picker is closed, the filter bar shows only the active filter's own count, not a breakdown of every project
    Given the backlog is shown with the registered projects "org-a/proj-a" and "org-b/proj-b", each with backlogged items
    When f is pressed
    And Down is pressed
    And Enter is pressed
    Then the filter bar's right label reads "1 items"
    And the filter bar does not show proj-b's own count

  Scenario: The filter bar shows "PROJECT: All" and the total item count while unfiltered
    Given the backlog is shown with 3 todo items
    Then the filter bar's left label reads "PROJECT: All"
    And the filter bar's right label reads "3 items"

  Scenario: The filter bar's item count is plural even when it is zero
    Given the store has no todo items anywhere
    When I switch to the backlog
    Then the filter bar's right label reads "0 items"

  Scenario Outline: The filter bar's row survives compositing in every backlog state, not just the widgets' own report of themselves
    Given the "<state>" screen state is rendered
    Then the filter bar's composited frame shows the left label's own text
    And the filter bar's composited frame shows the right label's own text

    Examples:
      | state                       |
      | backlog#normal              |
      | backlog#empty               |
      | backlog#empty-filtered      |
      | backlog#claude-unavailable  |
      | backlog#stacked             |
      | backlog#picker-open         |

  Scenario: An overall-empty backlog shows a calm message instead of a blank area
    Given the store has no todo items anywhere
    When I switch to the backlog
    Then the message "Nothing in the backlog." is shown in place of the list

  Scenario: A backlog filtered to a project with no items shows a message naming the filtered project, not the overall-empty message
    Given the store has todo items, all belonging to a project other than "lightcycle"
    When the backlog is filtered to "lightcycle"
    Then the message "No backlog items for lightcycle." is shown, with "lightcycle" in the text colour and the rest of the message in the dim colour
    And the hint "Press f to check All." is shown below the message

  Scenario: An item becoming available under the active filter replaces the filtered-empty message with the list
    Given the backlog is shown, filtered to "lightcycle", with no items matching that filter
    When a todo item under "lightcycle" is created
    And one poll interval elapses
    Then the list is shown in place of the message, with a row for the new item

  Scenario Outline: Each shortcut for the backlog with rows present appears in the footer, in order
    Given the backlog is shown with a todo item
    When the shortcut at position <position> in the footer's shortcut line is read
    Then its key is "<key>"
    And its action is "<action>"

    Examples:
      | position | key           | action          |
      | 1        | ↑↓            | move            |
      | 2        | enter/→       | explore in tree |
      | 3        | f             | filter          |
      | 4        | tab           | current work    |
      | 5        | ctrl-u/ctrl-d | scroll          |
      | 6        | q             | quit            |

  Scenario Outline: Each shortcut for the overall-empty backlog appears in the footer, in order
    Given the store has no todo items anywhere
    And I switch to the backlog
    When the shortcut at position <position> in the footer's shortcut line is read
    Then its key is "<key>"
    And its action is "<action>"

    Examples:
      | position | key | action       |
      | 1        | tab | current work |
      | 2        | q   | quit         |

  Scenario Outline: Each shortcut for the filtered-empty backlog appears in the footer, in order
    Given the backlog is shown, filtered to "lightcycle", with no items matching that filter
    When the shortcut at position <position> in the footer's shortcut line is read
    Then its key is "<key>"
    And its action is "<action>"

    Examples:
      | position | key | action       |
      | 1        | f   | filter       |
      | 2        | tab | current work |
      | 3        | q   | quit         |

  Scenario: The picker's own footer shows its own key hints while it is open
    Given the backlog is shown with the registered project "org-a/proj-a"
    When f is pressed
    Then the picker's footer reads "↑↓ move · enter apply · esc cancel"
