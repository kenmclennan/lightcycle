# Await-merge (you + driver)

A PR is green, comments resolved, and rebased on the tip of main - ready to merge. You merge it
(lightcycle never merges for you); the driver runs this skill to set it up and record the outcome.

1. `lc show STEP` for the item's pr artifact (type=pr); open it on GitHub.
2. Confirm CI is green and review comments are resolved; summarise the PR for the human.
3. The human merges it on GitHub - their call, their click.
4. The pool's PR monitor closes the item automatically once GitHub shows the merge; run
   `lc done STEP merged` yourself only if it has not caught up yet.
5. If it needs changes instead of merging: `lc done STEP changes` with a note saying exactly what
   to change so the next agent can act on it.

The merge is the human's irreducible act; you assist and do the bookkeeping. No emdashes.
