# Cleanup (you + driver, terminal)

The PR is merged; tidy up. No routes - the flow ends here. The step surfaces in `lc inbox`; the
driver runs this skill to do the close-out with you.

1. `lc done ITEM merged` - closes the item + its child steps (status closed, reason merged),
   removes the worktree (`.worktrees/ITEM`), and deletes the merged feature branch. Beads are
   kept, not deleted (the history is the measurement substrate).
2. `lc done STEP done` is not needed - cleanup is terminal and `lc done` closes the step.

No emdashes.
