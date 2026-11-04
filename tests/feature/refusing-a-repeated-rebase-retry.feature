Feature: Refusing a repeated rebase retry
  A stage that hands a failing check back to the CI stage after a rebase may do so once per
  check in a phase run; the second attempt for the same check is refused and the claim says
  which checks have already been retried.

  Scenario: A second rebase retry for the same check is refused
    Given a recheck pass that closed retried for the check "wf / test"
    And CI failed on "wf / test" again
    When the next recheck pass is claimed
    Then its claim lists "wf / test" as already retried
    And closing it retried for "wf / test" is refused
    And closing it broke is accepted
