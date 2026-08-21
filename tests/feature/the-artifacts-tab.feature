Feature: The Artifacts tab
  A node's Artifacts tab lists its non-internal artifacts, each labeled by its
  own type - internal bookkeeping artifacts are filtered out entirely, the
  same content-indicator rule the Hierarchy tab already uses. The tab is
  always present, even on a node with nothing viewable, so the Hierarchy /
  Log / Artifacts cycle stays the same three tabs on every node; a node with
  nothing to show gets a calm message in place of the list rather than a
  blank area. Arrow keys move the selection; confirming a selected artifact
  with Enter or → opens it in the viewer appropriate for its kind - which
  viewer that is is fully specified in the Artifact Viewer's own feature
  file, not here. Closing the list with Esc or ← returns to the node's hub
  exactly as it was.

  Scenario: Each non-internal artifact is labeled by its own type
    Given a node has artifacts of type "spec", "branch", and "pr"
    When I open its Artifacts tab
    Then each is shown labeled by its own type

  Scenario: Internal artifacts never appear in the list
    Given a node has both an internal artifact and a non-internal artifact
    When I open its Artifacts tab
    Then only the non-internal artifact is shown
    And the internal artifact does not appear

  Scenario: The type column widens to fit a type name longer than its historical fixed width, without truncating it
    Given a node has an artifact of type "code-review-findings"
    When I open its Artifacts tab
    Then that artifact is shown labeled by its full type "code-review-findings"

  @wip
  Scenario Outline: When an artifact row cannot fit unstacked, the value moves to a continuation line indented 2 characters and spanning the row without wrapping mid-word
    Given an artifact row whose type and the flexible minimum for value together exceed the row budget, on a terminal <at a width>
    When I open its Artifacts tab
    Then the type remains alone on the row's first line
    And the value appears on a continuation line indented 2 characters
    And no fragment of the value's prose is split mid-word

    Examples:
      | at a width                            |
      | just narrow enough to force stacking  |
      | just wide enough to clear the floor   |

  Scenario: A node with no viewable artifacts shows a calm message in place of the list
    Given a node has no non-internal artifacts
    When I open its Artifacts tab
    Then a calm message is shown in place of the list, not a blank area

  Scenario: The Artifacts tab is present even on a node with no viewable artifacts
    Given a node has no non-internal artifacts
    When its hub is open
    Then the Artifacts tab is present, alongside Hierarchy and Log

  Scenario: Down moves the artifact selection to the next entry
    Given the artifact list has more than one entry
    When Down is pressed
    Then the selection has moved to the next entry

  Scenario: Up moves the artifact selection to the previous entry
    Given the artifact list has more than one entry
    And the selection is not on the first entry
    When Up is pressed
    Then the selection has moved to the previous entry

  Scenario Outline: Confirming a selected artifact opens it in the viewer appropriate for its kind
    Given an artifact is selected in the list
    When <key> is pressed
    Then it opens in the viewer appropriate for its kind

    Examples:
      | key   |
      | Enter |
      | →     |

  Scenario Outline: Closing the artifact list returns to the hub view as it was
    Given I opened the artifact list from a node's hub view
    When I close it with <key>
    Then the hub view reappears as it was

    Examples:
      | key   |
      | Esc   |
      | ←     |
