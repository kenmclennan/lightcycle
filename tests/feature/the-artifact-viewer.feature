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
  from here too, the same as from any other depth in the map.

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
