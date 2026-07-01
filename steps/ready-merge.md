---
step: ready-merge
routes:
  merged: cleanup
  changes: build
signals:
  resets: changes
---

# Ready-merge (you + driver)

A PR is green, comments resolved, and rebased on the tip of main - ready to merge. You merge it
(the-grid never merges for you); the driver runs this skill to set it up and record the outcome.

1. `tg show TASK` for the story's pr artifact (type=pr); open it on GitHub.
2. Confirm CI is green and review comments are resolved; summarise the PR for the human.
3. The human merges it on GitHub - their call, their click.
4. After they merge: `tg done TASK merged` (-> cleanup).
5. If it needs more code instead of merging: `tg done TASK changes` (-> build) with a note saying
   exactly what to change so the next coder can act.

The merge is the human's irreducible act; you assist and do the bookkeeping. No emdashes.
