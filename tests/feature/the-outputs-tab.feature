Feature: The Outputs tab
  An item's Outputs tab lists what its work produced, one row per output name,
  showing the current value, the step that produced it and the pass it came
  from. Pull requests are rows too, one per phase, read from the item's phase
  runs. Records and internal bookkeeping never appear. The tab is always
  present on an item, even one with nothing produced yet, alongside
  Description, Workflow and Cost; an item with nothing to show gets a calm
  message in place of the list rather than a blank area. An output reworked
  across passes keeps one row with a +N marker; space expands the earlier
  versions directly under it, dim and indented, and space again collapses
  them. Arrow keys move the selection; confirming a row, a history row
  included, with Enter or → opens that version in the viewer appropriate for
  its kind - which viewer that is is fully specified in the Artifact Viewer's
  own feature file, not here. Closing the list with Esc or ← returns to the
  node's hub exactly as it was.

  Scenario: Each output is a row labeled by its own name
    Given a node has artifacts of type "spec", "branch", and "pr"
    When I open its Outputs tab
    Then each is shown labeled by its own type

  Scenario: Internal artifacts never appear in the outputs
    Given a node has both an internal artifact and a non-internal artifact
    When I open its Outputs tab
    Then only the non-internal artifact is shown
    And the internal artifact does not appear

  Scenario: The name column widens to fit a name longer than its historical fixed width, without truncating it
    Given a node has an artifact of type "code-review-findings"
    When I open its Outputs tab
    Then that artifact is shown labeled by its full type "code-review-findings"

  Scenario Outline: When an output row cannot fit unstacked, the value moves to a continuation line indented 2 characters and spanning the row without wrapping mid-word
    Given an artifact row whose type and the flexible minimum for value together exceed the row budget, on a terminal <at a width>
    When I open its Outputs tab
    Then the type remains alone on the row's first line
    And the value appears on a continuation line indented 2 characters
    And no fragment of the value's prose is split mid-word

    Examples:
      | at a width                            |
      | just narrow enough to force stacking  |
      | just wide enough to clear the floor   |

  Scenario: A node with no outputs shows a calm message in place of the list
    Given a node has no non-internal artifacts
    When I open its Outputs tab
    Then a calm message is shown in place of the list, not a blank area

  Scenario: The Outputs tab is present even on an item with no outputs
    Given an item has no non-internal artifacts
    When its hub is open
    Then the Outputs tab is present, alongside Description and Workflow

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

  Scenario Outline: Closing the outputs list returns to the hub view as it was
    Given I opened the artifact list from a node's hub view
    When I close it with <key>
    Then the hub view reappears as it was

    Examples:
      | key   |
      | Esc   |
      | ←     |

  Scenario: An output reworked across passes is one row with a +N marker, and space reveals the earlier version under it
    Given an item with a spec, a spec-phase PR, a code-phase PR and a spec reworked in a second pass
    When I open its Outputs tab
    Then the rows are the spec showing its newest value with "+1", then "pr (spec)", then "pr (code)"
    And no reflection, session or guidance row appears
    When space is pressed on the spec row
    Then the older spec version appears directly under the spec row, indented

  Scenario: A scheduled item's findings output is one row naming its producing step and pass, and Enter opens the text viewer
    Given a scheduled item with a findings output on its step
    When I open its Outputs tab
    Then there is one "findings" row showing its producing step and pass
    When Enter is pressed
    Then it opens in the viewer appropriate for its kind
