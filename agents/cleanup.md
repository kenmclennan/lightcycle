---
step: cleanup
---

# Cleanup (human step, terminal)

A human step: never spawned, no routes (the flow ends here). Its task surfaces in `tg mine`. The PR
is merged; tidy up.

1. `tg close STORY merged` - closes the story + its child tasks (status closed, reason merged),
   removes the worktree (`.worktrees/STORY`), and deletes the merged `grid/STORY` branch. Beads are
   kept, not deleted (the history is the measurement substrate).
2. `tg done TASK done` is not needed - cleanup is terminal and `tg close` closes the task.

No emdashes.
