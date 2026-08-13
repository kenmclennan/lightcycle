Feature: Backlog counts per registered project in one call
  A reader can ask, in one call, how many backlogged items each registered
  project has - including projects with zero items, which still appear rather
  than being dropped - plus a count of items with no project at all, and a
  total count of every backlogged item regardless of whether its project
  could be matched. The existing single-project backlog filter is unaffected
  and stays consistent with what this read reports.

  Scenario: Reading the backlog counts reports every registered project's own count
    Given the registered project "org-a/proj-a" with 2 backlogged items whose repo is "proj-a"
    And the registered project "org-b/proj-b" with 1 backlogged item whose repo is "proj-b"
    And the registered project "org-c/proj-c" with no backlogged items
    And 1 backlogged item with no repo artifact
    When the backlog counts are read
    Then project "proj-a" reports count 2
    And project "proj-b" reports count 1
    And project "proj-c" reports count 0

  Scenario: A registered project with zero backlogged items still appears, with count zero
    Given the registered project "org-c/proj-c" with no backlogged items
    When the backlog counts are read
    Then project "proj-c" reports count 0

  Scenario: Items with no repo artifact are reported as a separate unscoped count
    Given the registered project "org-a/proj-a" with 2 backlogged items whose repo is "proj-a"
    And 1 backlogged item with no repo artifact
    When the backlog counts are read
    Then the unscoped count is 1

  Scenario: A registered project is matched by the bare last segment of its identity, not the full identity
    Given the registered project "org-a/proj-a" with 2 backlogged items whose repo is "proj-a"
    When the backlog counts are read
    Then project "proj-a" reports count 2

  Scenario: The total counts every backlogged item, including ones matching no registered project
    Given the registered project "org-a/proj-a" with 2 backlogged items whose repo is "proj-a"
    And the registered project "org-b/proj-b" with 1 backlogged item whose repo is "proj-b"
    And 1 backlogged item with no repo artifact
    And 1 backlogged item whose repo is "typo-project", which matches no registered project
    When the backlog counts are read
    Then the total count is 5
    And the total count is greater than the sum of the project counts and the unscoped count

  Scenario Outline: The project value reported by the counts read stays consistent with the single-filter read
    Given the registered project "org-a/proj-a" with 2 backlogged items whose repo is "proj-a"
    And the registered project "org-b/proj-b" with 1 backlogged item whose repo is "proj-b"
    When the backlog counts are read
    And the backlog is read filtered to the reported project value for "<project>"
    Then the number of rows returned equals the count reported for "<project>"

    Examples:
      | project |
      | proj-a  |
      | proj-b  |

  Scenario: No registered projects and no backlogged items
    Given no registered projects
    And no backlogged items
    When the backlog counts are read
    Then the projects list is empty
    And the unscoped count is 0
    And the total count is 0
