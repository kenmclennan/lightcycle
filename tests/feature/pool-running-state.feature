Feature: Read-only pool-running-state use case
  A reader can ask whether the pool's run lock is currently held by a live
  process without acquiring the lock itself. The read never creates, writes,
  or removes the run lock file, so it can never block a real `lc start` from
  later acquiring that same lock.

  Scenario Outline: Reading the pool-running state reports status without touching the lock file
    Given <lock_state>
    When the pool-running state is read
    Then it reports the pool as <expected>
    And the run lock file is untouched

    Examples:
      | lock_state                                                        | expected    |
      | the run lock file records the pid of a live process               | running     |
      | no run lock file exists                                           | not running |
      | the run lock file records the pid of a process that is not alive  | not running |

  Scenario: Reading the pool-running state repeatedly never blocks a later real lock acquisition
    Given no run lock file exists
    When the pool-running state is read 3 times
    And a real run lock acquisition is then attempted
    Then the acquisition succeeds
