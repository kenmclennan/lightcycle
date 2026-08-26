Feature: The Artifact viewer
  Opened by confirming a selected artifact from a node's Artifacts tab, the
  viewer dispatches on the artifact's own kind. A text artifact opens
  full-screen within the dashboard, scrollable if it's longer than one page;
  an artifact whose kind the TUI doesn't recognise opens the same way, so no
  artifact is ever unopenable. A list artifact opens as its own scrollable
  list rather than a wall of text. URL and file-path artifacts hand off to an
  external program instead - the system's default browser, or the OS's own
  handler for that file type - and the TUI never sits in a screen for them:
  once the hand-off succeeds it shows a brief confirmation toast and returns
  straight to the artifact list; if it fails, a clear message is shown
  instead of a silent failure or a crash. Closing a sit-in viewer (text or
  list) with Esc or ← returns to the artifact list with that artifact still
  selected. Tab still jumps straight to the backlog, or back to current work,
  from here too, the same as from any other depth in the map. Like every
  other screen, both sit-in viewers carry the shared status bar - pool,
  Claude availability, version, upgrade-when-available - visible from their
  own first frame, before any poll tick, and kept live by the same poll the
  rest of the dashboard uses. A sit-in viewer's header names the artifact by
  its type in the cyan colour, its id dim beside it, and carries a
  right-aligned segment of its own per kind - a list artifact's segment
  counts the items inside it, and a text artifact's segment shows where it
  sits among the node's own artifacts.

  Scenario Outline: A text artifact opens full-screen when selected
    Given an artifact declares kind "text"
    When I select it with <key>
    Then it opens full-screen
    And it is scrollable if longer than one page

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: Scrolling a text artifact reaches the end without truncation
    Given a text artifact longer than one page is open
    When I scroll to the end
    Then the whole artifact can be read without truncation

  Scenario Outline: An artifact of an unrecognised kind opens in the text viewer instead of failing
    Given an artifact declares a kind the TUI does not recognise
    When I select it with <key>
    Then it opens in the text viewer, not an error

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: A URL artifact opens in the system's default browser when selected
    Given an artifact declares kind "url"
    When I select it with <key>
    Then it opens in the system's default browser

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: Opening a URL artifact successfully shows a confirmation toast and returns to the list
    Given a URL artifact opens successfully in the browser
    When that happens
    Then a brief confirmation toast is shown
    And the artifact list reappears

  Scenario: A URL artifact that fails to open shows a clear message instead of failing silently
    Given a URL artifact fails to open, e.g. no browser is available
    When that happens
    Then a clear message is shown, not a silent failure

  Scenario Outline: A file-path artifact opens via the OS's default handler when selected
    Given an artifact declares kind "filepath"
    When I select it with <key>
    Then it opens via the OS's default handler for that file type

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: Opening a file-path artifact successfully shows a confirmation toast and returns to the list
    Given a file-path artifact opens successfully in its application
    When that happens
    Then a brief confirmation toast is shown
    And the artifact list reappears

  Scenario Outline: A file-path artifact whose file no longer exists shows a clear message instead of failing silently
    Given a file-path artifact whose file no longer exists at that path
    When I select it with <key>
    Then a clear message is shown, not a silent failure or crash

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: A list artifact displays as its own scrollable list, not raw text
    Given an artifact declares kind "list"
    When I select it with <key>
    Then it displays as its own scrollable list, not as raw text

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario: Scrolling a list artifact longer than one screen reaches every item
    Given a list artifact with more items than fit on one screen is open
    When I scroll to the end
    Then every item can be reached

  Scenario Outline: The header colours only the artifact's type, leaving its id dim
    Given an artifact declares kind "<kind>"
    When I select it with Enter
    Then the header's type segment is shown in the cyan colour
    And the header's id segment is shown in the dim colour, not cyan

    Examples:
      | kind |
      | text |
      | list |

  Scenario Outline: A text artifact's header shows its position among the node's artifacts
    Given a node has <total> non-internal artifacts
    And I open the text artifact at position <position> in that list
    When it opens
    Then the header's right-aligned segment reads "<position> / <total>"

    Examples:
      | position | total |
      | 1        | 1     |
      | 2        | 3     |

  Scenario Outline: Closing an open artifact returns to the list with it still selected
    Given I opened a "<kind>" artifact from the list
    When I close it with <key>
    Then the artifact list reappears with that artifact still selected

    Examples:
      | kind | key |
      | text | Esc |
      | text | ←   |
      | list | Esc |
      | list | ←   |

  Scenario: Tab jumps straight to the backlog from an open artifact viewer, bypassing Esc/← back-navigation
    Given the artifact viewer is open, showing a text artifact
    When Tab is pressed
    Then the backlog is shown in place of the viewer

  Scenario Outline: The status bar renders on the Artifact Viewer's first frame, before any poll tick
    Given an artifact declares kind "<kind>"
    When I select it with Enter
    Then the status bar is not blank, showing the pool status, the Claude-availability status, and the installed version

    Examples:
      | kind |
      | text |
      | list |

  Scenario Outline: The status bar shows the upgrade indicator on the Artifact Viewer when a newer version is available
    Given a newer version is available
    And an artifact declares kind "<kind>"
    When I select it with Enter
    Then the status bar shows the upgrade indicator with that version

    Examples:
      | kind |
      | text |
      | list |

  Scenario Outline: The status bar stays live on the Artifact Viewer by polling on the fixed interval
    Given an artifact declares kind "<kind>"
    And I select it with Enter
    When the pool or breaker state changes
    And one poll interval elapses
    Then the status bar reflects the changed state

    Examples:
      | kind |
      | text |
      | list |
