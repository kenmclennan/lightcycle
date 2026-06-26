---
step: ready-merge
routes:
  merged: cleanup
  changes: build
---

# Ready-merge (human step)

A human step: never spawned. Its tasks surface in `tg mine` for the human/driver to act on. The PR
is green, comments resolved, and rebased on the tip of main - it is ready to merge.

1. `tg show TASK` for the story's pr artifact (type=pr); open it on GitHub.
2. Merge it on GitHub (the human's call - the-grid never merges for you).
3. After merging: `tg done TASK merged` (-> cleanup).
4. If instead it needs more code (not ready after all): `tg done TASK changes` (-> build); leave a
   note saying exactly what to change so the next coder can act.

No emdashes.
