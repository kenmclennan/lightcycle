Feature: The Description tab
  A node's Description tab shows its full prose description, wrapped to the
  pane at full contrast, with no truncation - the description used to live
  as an unbounded line in the header, which is what let it push the tab
  strip and the whole tab body off the bottom of the screen; it now lives
  here instead, scrollable, with the header fixed regardless of its length.
  The tab is always present on an item, even one with no description,
  alongside Hierarchy and Artifacts - Description belongs to items only,
  never to a step; an item with nothing to show gets a calm message in place
  of the text rather than a blank area. Scrolling uses the same keys the
  Log tab uses - up/down and Ctrl-U/Ctrl-D - and a description longer than
  the pane opens scrolled to the top, not the bottom. Nothing here is
  editable.

  Scenario: A node's description is shown in full, at full contrast
    Given a node has a description
    When I open its Description tab
    Then the full description text is shown
    And it renders in the text colour, not the dim colour

  Scenario: A node with no description shows a calm message in place of the text
    Given a node has no description
    When I open its Description tab
    Then a calm message is shown in place of the text, not a blank area

  @wip
  Scenario: The Description tab is present even on an item with no description
    Given an item has no description
    When its hub is open
    Then the Description tab is present, alongside Hierarchy and Artifacts

  Scenario: A description longer than the pane opens scrolled to the top, not the bottom
    Given a node has a description longer than the pane
    When I open its Description tab
    Then the view is scrolled to the top
    And no character of the description is cut off

  Scenario: Down scrolls the description forward
    Given a node has a description longer than the pane
    When I open its Description tab
    And Down is pressed
    Then the view has scrolled forward

  Scenario: Up scrolls the description back
    Given a node has a description longer than the pane
    And I open its Description tab
    And the view has scrolled forward
    When Up is pressed
    Then the view has scrolled back

  Scenario: Ctrl-D fast-scrolls the description a full screen forward
    Given a node has a description longer than the pane
    When I open its Description tab
    And Ctrl-D is pressed
    Then the view moves a full screen, not one line

  Scenario: Ctrl-U fast-scrolls the description a full screen back
    Given a node has a description longer than the pane
    When I open its Description tab
    And Ctrl-D is pressed
    And Ctrl-U is pressed
    Then the view is scrolled back to where it started
