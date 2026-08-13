Feature: The dashboard adopts the design system's visual vocabulary
  Every screen item cites the design system for its own rows, but the chrome
  around those rows - the bordered frame, the tab strip, the footer's
  two-line structure - and the shared state-to-glyph-and-colour, column-grid
  vocabulary itself, belonged to no item. This gives both an owner, so later
  screens render into an existing vocabulary instead of each re-deriving
  colours, icons, and grids independently. No behaviour changes: only how
  the dashboard is framed, and what shared token values are available to
  render into.

  @wip
  Scenario: The dashboard renders inside a bordered frame
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then the screen is framed on all four edges by a solid border in the border colour

  @wip
  Scenario: The tab strip shows the current-work tab emphasised and the backlog tab dim
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then the tab strip reads "Current work · Backlog"
    And the "Current work" tab is bold and in the cyan colour
    And the "Backlog" tab is in the dim colour

  @wip
  Scenario: Pressing Tab does not change which tab is emphasised
    Given the dashboard has launched
    When Tab is pressed
    Then the "Current work" tab is still the emphasised tab

  @wip
  Scenario: A table's selection cursor uses the design system's selected-row styling
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then a selected row's background is the selected-row colour
    And a selected row's foreground is the cyan colour

  @wip
  Scenario: The footer occupies two lines styled by the design system
    Given the lightcycle store is reachable
    When I launch the dashboard
    Then the footer occupies two one-row lines, a status line above a shortcut line
    And the footer's top border is in the border colour
    And the footer's background is the bg colour, not the panel colour

  @wip
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

  @wip
  Scenario: The dependency-blocked needs-attention state adds the amber chain-link without losing the red dot
    Given the shared state vocabulary
    When the glyph and colour for the dependency-blocked needs-attention state are looked up
    Then its first glyph and colour are the same red dot as the plain needs-attention state
    And it additionally carries an amber chain-link glyph

  @wip
  Scenario: The shared vocabulary defines the priority list's column order
    Given the shared column grids
    When the priority list's column order is read
    Then it is cursor, icon, id, project, title, step, time

  @wip
  Scenario: The shared vocabulary defines the backlog's column order
    Given the shared column grids
    When the backlog's column order is read
    Then it is cursor, id, project, title
