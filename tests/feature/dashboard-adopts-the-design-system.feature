Feature: The dashboard adopts the design system's visual vocabulary
  Every screen item cites the design system for its own rows, but the chrome
  around those rows - the bordered frame, the tab strip, the footer's
  two-line structure - and the shared state-to-glyph-and-colour, column-grid
  vocabulary itself, belonged to no item. This gives both an owner, so later
  screens render into an existing vocabulary instead of each re-deriving
  colours, icons, and grids independently. The footer's shortcut line is part
  of that chrome: rather than a fixed bar showing every key from every
  screen, or a curated subset the operator can't trust is complete, it
  renders whatever is actually valid right now, supplied through a mechanism
  a later screen can call with its own set - at this point the dashboard is
  the only reachable screen, so what renders is the global keyboard
  shortcuts list, in order, exactly as the wireframe's own footer shows it.
  No behaviour changes: only how the dashboard is framed, and what shared
  token values are available to render into.

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

  Scenario: Pressing Tab does not change which tab is emphasised
    Given the dashboard has launched
    When Tab is pressed
    Then the "Current work" tab is still the emphasised tab

  Scenario: A table's selection cursor uses the design system's selected-row styling
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then a selected row's background is the selected-row colour
    And the selection cursor glyph is rendered in the cyan colour

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
      | active          | ▸     | cyan   |
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

  @wip
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
