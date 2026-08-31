Feature: A theme seeds and guards its items
  A theme contributes two things to the items filed beneath it that a bare
  item cannot give itself. Filing a new item under a theme seeds it with
  the theme's own repo, when the item states none of its own, so every
  item under the same theme starts pointing at the same place without
  having to say so each time. And a theme refuses to close while any item
  beneath it is still open, leaving the theme and every one of those items
  exactly as they were - the reverse of an item's own close, which force-
  closes whatever steps remain open beneath it.

  @wip
  Scenario: Creating an item under a theme with a repo inherits that repo, when the item states none of its own
    Given a theme with repo "lightcycle"
    When I create an item under that theme, with no repo of its own
    Then the item's repo is "lightcycle"

  @wip
  Scenario: An item's own repo overrides its theme's, when both are given
    Given a theme with repo "lightcycle"
    When I create an item under that theme, with its own repo "other"
    Then the item's repo is "other"

  @wip
  Scenario: A theme with no repo leaves a new item under it untagged
    Given a theme with no repo
    When I create an item under that theme, with no repo of its own
    Then the item has no repo artifact at all

  @wip
  Scenario: A theme with an open item beneath it refuses to close, and leaves the theme and the item exactly as they were
    Given a theme with one open item beneath it
    When I close the theme with outcome "done"
    Then the command is rejected
    And the refusal names the open item
    And the theme is still ready
    And the item is still backlogged
