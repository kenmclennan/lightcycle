Feature: The Log tab
  The Log tab tails the current step's log directly, bypassing the poll loop, so new
  lines appear as fast as the worker writes them. What it renders depends on the step
  behind it: a running step gets a live-following tail seeded with whatever it's
  already written, a step with no worker - human, or not yet started - shows a message
  instead of a blank or broken pane, and a step that's already done shows its most
  recently captured output, up to the retained window, as a static, scrollable read
  with no live-tail indicators. A step
  that finishes while its live log is open makes that transition visible rather than
  just going silent, without clearing what was already shown. Scrolling up never stops
  a running tail, and Ctrl-U/Ctrl-D fast-scroll a full screen at a time in either state,
  live or historical.

  Every log line - live or historical, most-recently-tailed or not - renders in the
  same text colour; brightness carries no meaning in the log. The one visual cue that
  a tail is live at all is a trailing cursor glyph in the cyan colour, carried by
  whichever line was written most recently, moving to each new line as it arrives and
  disappearing once the step finishes.

  Scenario: Opening a running step's Log tab shows the output already written, not just new lines
    Given the current step is being performed by a worker and has already written several lines
    When I open its Log tab
    Then the lines already written are shown

  Scenario: A running step's log streams new lines without a manual refresh
    Given the current step is being performed by a worker
    When I open its Log tab
    And the worker writes a new line to the log
    Then the new line appears without a manual refresh

  Scenario: No cursor is shown before anything has been tailed
    Given the current step is being performed by a worker
    When I open its Log tab
    Then no cursor glyph is shown

  Scenario: The most recently tailed line carries the live cursor, from the first frame the tab renders
    Given the live log is open and following the tail
    Then the last line of the log ends with a trailing cursor glyph in the cyan colour
    And every displayed log line renders in the text colour, not the dim colour

  Scenario: The live cursor moves to the newest line as new lines arrive, without any colour change
    Given the live log is open and following the tail
    When a new line arrives
    Then the new last line ends with a trailing cursor glyph in the cyan colour
    And the line that previously carried the cursor no longer carries it
    And that previous line still renders in the text colour, not the dim colour

  Scenario: The live cursor disappears once the step finishes
    Given the live log is open and following the tail
    When the worker completes
    Then no line carries the cursor glyph

  Scenario: The live tail auto-scrolls to keep a new line visible
    Given the live log is open and following the tail
    When a new line arrives
    Then the view auto-scrolls to keep it visible

  Scenario Outline: A step with nothing live to stream shows a message instead of a blank pane
    Given <condition>
    When I open its Log tab
    Then I see a message saying there's nothing live to stream
    And no blank or broken pane is shown

    Examples:
      | condition                                         |
      | the current step is a human step, with no worker   |
      | the current step hasn't started yet, still queued  |

  Scenario Outline: Returning to the node from the Log tab
    Given the current step is a human step, with no worker
    When I open its Log tab
    And <key> is pressed
    Then the hub closes

    Examples:
      | key |
      | Esc |
      | ←   |

  Scenario: Scrolling up shows earlier lines without stopping the live tail
    Given the live log is open
    When I scroll up
    Then I see earlier lines from the current buffer
    And the live tail keeps running

  Scenario: A new line arriving while scrolled up doesn't yank the view back to the bottom
    Given the live log is open and I've scrolled up
    When a new line arrives
    Then it's added to the buffer
    And my scroll position is unchanged

  Scenario: Ctrl-D fast-scrolls the live log a full screen forward
    Given the live log's buffer is longer than one screen
    When Ctrl-D is pressed
    Then the view moves a full screen, not one line

  Scenario: Ctrl-U fast-scrolls the live log a full screen back
    Given the live log's buffer is longer than one screen
    When Ctrl-D is pressed
    And Ctrl-U is pressed
    Then the view is scrolled back to where it started

  Scenario: The log shows the step has finished when it completes while being watched
    Given the live log is open
    When the worker completes
    Then the view clearly indicates the step has finished
    And it doesn't just go silent

  Scenario: The finished step's accumulated log stays visible, not cleared
    Given the step has finished while its log was open
    When I look at the log
    Then it still shows the output accumulated up to completion

  Scenario: Opening a done step's Log tab shows its most recently captured output
    Given the current step is done
    When I open its Log tab
    Then it shows the most recently captured log output, up to the retained window

  Scenario: A done step's log shows no live-tail indicators
    Given a done step's log is open
    When I view it
    Then no live indicator is shown
    And there is no auto-scroll, since nothing new will arrive

  Scenario: Ctrl-D fast-scrolls a done step's log a full screen forward, same as the live log
    Given a done step's log is longer than one screen
    When Ctrl-D is pressed
    Then the view moves a full screen, not one line

  Scenario: Ctrl-U fast-scrolls a done step's log a full screen back, same as the live log
    Given a done step's log is longer than one screen
    When Ctrl-D is pressed
    And Ctrl-U is pressed
    Then the view is scrolled back to where it started

  Scenario: A line wider than the pane wraps instead of being cut off
    Given the current step is being performed by a worker and has already written a line wider than the pane
    When I open its Log tab
    Then the wide line's full text is reachable across more than one painted row

  Scenario: A malformed log line is shown instead of crashing the tab or vanishing
    Given the current step is being performed by a worker and has already written a malformed line
    When I open its Log tab
    Then the malformed line is shown as its own line

  Scenario: Thinking lines are shown by default
    Given the live log is open and following the tail, with a thinking line in its output
    Then the thinking line is visible

  Scenario: Pressing t hides thinking lines, and pressing it again restores them
    Given the live log is open and following the tail, with a thinking line in its output
    When I press t
    Then the thinking line is hidden
    When I press t
    Then the thinking line is visible

  Scenario: The live cursor stays on the last visible line when the newest event is a hidden thinking line
    Given the live log is open and following the tail, with thinking hidden
    When a thinking-only line arrives
    Then the cursor still marks the previous last visible line

  Scenario: The live cursor stays on the last visible line when the newest event produces no line at all
    Given the live log is open and following the tail
    When a thinking-token-only event arrives
    Then the cursor still marks the previous last visible line
