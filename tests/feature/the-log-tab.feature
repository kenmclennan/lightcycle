Feature: The Log tab
  The Log tab tails the current step's log directly, bypassing the poll loop, so new
  lines appear as fast as the worker writes them. What it renders depends on the step
  behind it: a running step gets a live-following tail seeded with whatever it's
  already written, a step with no worker - human, or not yet started - shows a message
  instead of a blank or broken pane, and a step that's already done shows its full
  accumulated output as a static, scrollable read with no live-tail indicators. A step
  that finishes while its live log is open makes that transition visible rather than
  just going silent, without clearing what was already shown. Scrolling up never stops
  a running tail, and Ctrl-U/Ctrl-D fast-scroll a full screen at a time in either state,
  live or historical.

  @wip
  Scenario: Opening a running step's Log tab shows the output already written, not just new lines
    Given the current step is being performed by a worker and has already written several lines
    When I open its Log tab
    Then the lines already written are shown

  @wip
  Scenario: A running step's log streams new lines without a manual refresh
    Given the current step is being performed by a worker
    When I open its Log tab
    And the worker writes a new line to the log
    Then the new line appears without a manual refresh

  @wip
  Scenario: The live tail auto-scrolls to keep a new line visible
    Given the live log is open and following the tail
    When a new line arrives
    Then the view auto-scrolls to keep it visible

  @wip
  Scenario Outline: A step with nothing live to stream shows a message instead of a blank pane
    Given <condition>
    When I open its Log tab
    Then I see a message saying there's nothing live to stream
    And no blank or broken pane is shown

    Examples:
      | condition                                         |
      | the current step is a human step, with no worker   |
      | the current step hasn't started yet, still queued  |

  @wip
  Scenario: Scrolling up shows earlier lines without stopping the live tail
    Given the live log is open
    When I scroll up
    Then I see earlier lines from the current buffer
    And the live tail keeps running

  @wip
  Scenario: A new line arriving while scrolled up doesn't yank the view back to the bottom
    Given the live log is open and I've scrolled up
    When a new line arrives
    Then it's added to the buffer
    And my scroll position is unchanged

  @wip
  Scenario: Ctrl-D fast-scrolls the live log a full screen forward
    Given the live log's buffer is longer than one screen
    When Ctrl-D is pressed
    Then the view moves a full screen, not one line

  @wip
  Scenario: Ctrl-U fast-scrolls the live log a full screen back
    Given the live log's buffer is longer than one screen
    When Ctrl-D is pressed
    And Ctrl-U is pressed
    Then the view is scrolled back to where it started

  @wip
  Scenario: The log shows the step has finished when it completes while being watched
    Given the live log is open
    When the worker completes
    Then the view clearly indicates the step has finished
    And it doesn't just go silent

  @wip
  Scenario: The finished step's accumulated log stays visible, not cleared
    Given the step has finished while its log was open
    When I look at the log
    Then it still shows the output accumulated up to completion

  @wip
  Scenario: Opening a done step's Log tab shows its complete captured output
    Given the current step is done
    When I open its Log tab
    Then it shows the complete log output captured from that step's run

  @wip
  Scenario: A done step's log shows no live-tail indicators
    Given a done step's log is open
    When I view it
    Then no live indicator is shown
    And there is no auto-scroll, since nothing new will arrive

  @wip
  Scenario: Ctrl-D fast-scrolls a done step's log a full screen forward, same as the live log
    Given a done step's log is longer than one screen
    When Ctrl-D is pressed
    Then the view moves a full screen, not one line

  @wip
  Scenario: Ctrl-U fast-scrolls a done step's log a full screen back, same as the live log
    Given a done step's log is longer than one screen
    When Ctrl-D is pressed
    And Ctrl-U is pressed
    Then the view is scrolled back to where it started
