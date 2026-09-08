Feature: The Cost tab
  Every agent step records what it consumed - turns, tokens, and cost - and
  none of it was visible anywhere in the TUI before this tab. A step's Cost
  tab and an item's Cost tab are both appended last in their tab strip, after
  Artifacts and after Log respectively, so the existing Workflow-is-one-press
  invariant is unaffected. A step's rendering discriminates on four states,
  not three: a human step has no cost fields at all, since the concept
  doesn't apply to a human gate; an agent step that hasn't produced a turn
  yet shows its own "hasn't run yet" empty state, distinct from the human
  case; an agent step that ran but has no recorded cost shows its turns,
  tokens, and cache hit rate - real attribution data, independent of pricing
  - with an explicit "not recorded" for cost and cost basis, never $0.00; an
  agent step that ran with a recorded cost shows every figure. An item's Cost
  tab sums the same figures across every one of its steps, every pass
  included, excluding human steps entirely, plus a per-stage subtotal
  ordered by spend so an item's spend is legible at a glance; its
  cost-per-turn divides only by the turns belonging to steps with a known
  cost basis.

  Scenario: A human step's Cost tab shows no cost fields at all
    Given a human step, its hub open
    When I open its Cost tab
    Then no cost stats table is shown
    And a message says this step has no cost to show

  Scenario: An agent step that hasn't run yet shows a distinct empty state from the human case
    Given an agent step that never ran, its hub open
    When I open its Cost tab
    Then no cost stats table is shown
    And a message says this step hasn't run yet

  Scenario: An agent step with a recorded cost shows cost, cost basis, turns, tokens, and cache hit rate
    Given an agent step with a recorded cost, its hub open
    When I open its Cost tab
    Then its cost is shown
    And its cost basis is shown
    And its turns are shown
    And its input, output, cache-read, and cache-creation tokens are all shown
    And its cache hit rate is shown, stated as cache-read over cache-read plus cache-creation plus input

  Scenario: An agent step's Cost tab includes its per-tool table of calls and bytes
    Given an agent step with a recorded cost and tool usage, its hub open
    When I open its Cost tab
    Then each tool's calls and bytes are shown

  Scenario: A step that ran but made no tool calls shows a message instead of an empty table
    Given an agent step with a recorded cost and no tool usage, its hub open
    When I open its Cost tab
    Then a message says no tool calls were recorded for this step

  Scenario: An agent step that ran but has no recorded cost shows "not recorded", never $0.00
    Given an agent step with turns but no recorded cost, its hub open
    When I open its Cost tab
    Then its turns are shown
    And its input, output, cache-read, and cache-creation tokens are all shown
    And its cost reads "not recorded"
    And no "$0.00" is shown anywhere on the tab

  Scenario: An item's Cost tab sums every step's usage across every pass, with a per-stage subtotal ordered by spend
    Given an item whose steps span two passes with recorded costs at different stages, its hub open
    When I open its Cost tab
    Then its total turns and cost sum every step across both passes
    And the per-stage subtotals are ordered with the highest-spend stage first

  Scenario: An item's per-stage subtotal for a stage with no recorded cost reads "not recorded", never $0.00
    Given an item with an agent step that ran but has no recorded cost, its hub open
    When I open its Cost tab
    Then that stage's row reads "not recorded"
    And no "$0.00" is shown anywhere on the tab

  Scenario: An item's Cost tab excludes human steps from the rollup entirely
    Given an item with a human gate step and an agent step with a recorded cost, its hub open
    When I open its Cost tab
    Then its total turns equal the agent step's turns alone

  Scenario: An item with no agent step run yet shows an empty state, not a zeroed total
    Given an item with no steps that have run, its hub open
    When I open its Cost tab
    Then no cost stats table is shown
    And a message says this item has no usage to show yet

  Scenario: The Cost tab is the last tab in an item's strip
    Given an item, its hub open
    Then its tab strip's last tab is "Cost"

  Scenario: The Cost tab is the last tab in a step's strip
    Given a step, its hub open
    Then its tab strip's last tab is "Cost"
