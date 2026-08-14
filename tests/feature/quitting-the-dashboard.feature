Feature: Quitting the dashboard
  The operator can exit the dashboard from the keyboard at any time, from the
  one screen the dashboard can currently reach, without needing to remember
  more than one key.

  @wip
  Scenario Outline: Pressing a quit key exits the dashboard
    Given the dashboard has launched
    When the "<key>" key is pressed
    Then the dashboard exits

    Examples:
      | key    |
      | q      |
      | ctrl+c |
