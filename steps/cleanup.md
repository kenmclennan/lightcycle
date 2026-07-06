# Cleanup (you + driver, terminal)

The PR is merged; tidy up. No routes - the flow ends here. The task surfaces in `tg inbox`; the
driver runs this skill to do the close-out with you.

1. `tg close STORY merged` - closes the story + its child tasks (status closed, reason merged),
   removes the worktree (`.worktrees/STORY`), and deletes the merged feature branch. Beads are
   kept, not deleted (the history is the measurement substrate).
2. `tg done TASK done` is not needed - cleanup is terminal and `tg close` closes the task.

No emdashes.
