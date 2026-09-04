Feature: The dashboard adopts the design system's visual vocabulary
  Every screen item cites the design system for its own rows, but the chrome
  around those rows - the bordered frame, the tab strip, the footer's
  two-line structure - and the shared state-to-glyph-and-colour, column-grid
  vocabulary itself, belonged to no item. This gives both an owner, so later
  screens render into an existing vocabulary instead of each re-deriving
  colours, icons, and grids independently. That includes the row surface
  itself: every wireframe gives only the selected row its own background
  rule and leaves every other row to inherit the terminal's own `--bg`, so a
  table that sets no background rule of its own is not neutral - it lets
  whatever the underlying widget defaults to show through instead, and that
  is this feature's to guard against, not any one screen's own item. The
  footer's shortcut line is part of that chrome: rather than a fixed bar
  showing every key from every screen, or a curated subset the operator
  can't trust is complete, it
  renders whatever is actually valid right now, supplied through a mechanism
  a later screen can call with its own set - at this point the dashboard is
  the only reachable screen, so what renders is the global keyboard
  shortcuts list, in order, exactly as the wireframe's own footer shows it.
  No behaviour changes: only how the dashboard is framed, and what shared
  token values are available to render into. The tab strip's own emphasis
  is chrome too: which of its two tabs is bold-and-cyan versus dim follows
  whichever top-level screen Tab last switched to, a behaviour the backlog
  screen (see the-backlog-screen.feature) introduces once a second top-level
  screen exists for Tab to switch to.

  Scenario: The dashboard renders inside a bordered frame
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then the screen is framed on all four edges by a solid border in the border colour

  Scenario: The tab strip shows the current-work tab emphasised and the backlog tab dim
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then the tab strip reads "Current work · Backlog"
    And the "Current work" tab is bold and in the cyan colour
    And the "Backlog" tab is in the dim colour

  Scenario: Pressing Tab moves the emphasis from the Current work tab to the Backlog tab
    Given the dashboard has launched
    When Tab is pressed
    Then the "Backlog" tab is bold and in the cyan colour
    And the "Current work" tab is in the dim colour

  Scenario: Pressing Tab again moves the emphasis back to the Current work tab
    Given the dashboard has launched
    When Tab is pressed
    And Tab is pressed
    Then the "Current work" tab is bold and in the cyan colour
    And the "Backlog" tab is in the dim colour

  Scenario: A table's selection cursor uses the design system's selected-row styling
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then a selected row's background is the selected-row colour
    And the selection cursor glyph is rendered in the cyan colour
    And selecting a row changes its background only, leaving every cell its own colour
    And a selected row's title is the text colour, not the cyan a coloured cell carries

  Scenario Outline: Every row not under the selection cursor paints the shared bg colour, never a widget's own default row surface
    Given the "<state>" screen state is rendered
    Then every row in its list area, except the one under the selection cursor, has a background of the bg colour

    Examples:
      | state                             |
      | priority-list#normal              |
      | priority-list#claude-unavailable  |
      | backlog#normal                    |
      | hub#artifacts                     |
      | artifact-viewer#list              |
      | artifact-viewer#text              |

  Scenario: The footer occupies two lines styled by the design system
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then the footer occupies two one-row lines, a status line above a shortcut line
    And the footer's top border is in the border colour
    And the footer's background is the bg colour, not the panel colour

  Scenario Outline: Each global shortcut appears in the footer's shortcut line at launch, in order
    Given the dashboard has launched
    When the shortcut at position <position> in the footer's shortcut line is read
    Then its key is "<key>"
    And its action is "<action>"

    Examples:
      | position | key           | action  |
      | 1        | ↑↓            | move    |
      | 2        | enter/→       | open    |
      | 3        | tab           | backlog |
      | 4        | ctrl-u/ctrl-d | scroll  |
      | 5        | q             | quit    |

  Scenario: Every shortcut's key text is bold and in the text colour, and its action label is in the dim colour
    Given the dashboard has launched
    Then every key in the footer's shortcut line is bold and in the text colour
    And every action label in the footer's shortcut line is in the dim colour

  Scenario: The shortcut line's content can be replaced through its update mechanism
    Given the dashboard has launched
    When the footer's shortcut line is given a different list of shortcuts
    Then the footer's shortcut line renders that new list instead of the global shortcuts

  Scenario Outline: The shared vocabulary's colour tokens hold their exact values
    Given the shared colour tokens
    When the "<token>" colour token is read
    Then its value is "<hex>"

    Examples:
      | token       | hex     |
      | bg          | #0c0c0f |
      | panel       | #101014 |
      | border      | #3a3a42 |
      | text        | #d8d8dc |
      | dim         | #6e6e78 |
      | cyan        | #5fd7e0 |
      | amber       | #e0a95f |
      | red         | #e05f6b |
      | selected-bg | #1c2a2c |

  Scenario Outline: Each state's shared vocabulary pairs a colour with its own glyph
    Given the shared state vocabulary
    When the glyph and colour for the "<state>" state are looked up
    Then the glyph is "<glyph>"
    And the colour is the <colour> colour

    Examples:
      | state           | glyph | colour |
      | needs-attention | ●     | red    |
      | active          | ◆     | cyan   |
      | queued          | ○     | dim    |

  Scenario: The dependency-blocked needs-attention state adds the amber chain-link without losing the red dot
    Given the shared state vocabulary
    When the glyph and colour for the dependency-blocked needs-attention state are looked up
    Then its first glyph and colour are the same red dot as the plain needs-attention state
    And it additionally carries an amber chain-link glyph

  Scenario: The shared vocabulary defines the priority list's column order
    Given the shared column grids
    When the priority list's column order is read
    Then it is cursor, icon, id, project, title, step, time

  Scenario: The shared vocabulary defines the backlog's column order
    Given the shared column grids
    When the backlog's column order is read
    Then it is cursor, id, project, title

  Scenario Outline: The shared vocabulary classifies each row-grid column as glyph, atomic, or flexible
    Given the shared row-grid sizing rule
    When the "<column>" column's kind is looked up
    Then its kind is <kind>

    Examples:
      | column  | kind     |
      | cursor  | glyph    |
      | icon    | glyph    |
      | content | glyph    |
      | id      | atomic   |
      | project | atomic   |
      | step    | atomic   |
      | role    | atomic   |
      | type    | atomic   |
      | time    | atomic   |
      | title   | flexible |
      | value   | flexible |

  Scenario: A glyph column's width is fixed and can never overflow
    Given the shared row-grid sizing rule
    Then the cursor column's width is fixed at 2 characters
    And the icon column's width is fixed at 4 characters
    And the content column's width is fixed at 2 characters

  Scenario: An atomic column's width is the longest value across the whole list, not just the rows currently on screen
    Given the shared row-grid sizing rule
    Then an atomic column's width is recomputed from every row in the list, not only the rows currently visible

  Scenario: An atomic column never truncates and never wraps its content, however long
    Given the shared row-grid sizing rule
    Then an atomic column has no overflow behaviour that cuts or wraps a value

  Scenario: A flexible column never narrows below its 24-character minimum
    Given the shared row-grid sizing rule
    Then a flexible column's minimum width is 24 characters

  Scenario Outline: A terminal too narrow for a grid's stacked layout shows a message instead of a corrupted grid
    Given the <screen> is open
    When the terminal is narrower than the grid's floor width
    Then a single message, centred and in the dim colour, names the width the grid needs
    And the footer is still shown, so the operator can still quit

    Examples:
      | screen        |
      | Priority List |
      | Backlog       |
      | Hierarchy tab |
      | Artifacts tab |

  Scenario Outline: The footer's shared vocabulary pairs a colour with its own glyph for each status token
    Given the shared footer status vocabulary
    When the glyph and colour for the "<token>" footer status are looked up
    Then the glyph is "<glyph>"
    And the colour is the <colour> colour

    Examples:
      | token              | glyph | colour |
      | pool-running       | ●     | cyan   |
      | pool-stopped       | ○     | dim    |
      | claude-available   | ●     | cyan   |
      | claude-unavailable | ⊘     | red    |
      | upgrade-available  | ⬆     | amber  |
