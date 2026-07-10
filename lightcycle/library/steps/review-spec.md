---
accepts:
  spec: required
---

# Review-spec (you + driver)

A spec is waiting for review before work proceeds. You decide; the driver runs this skill to help
you and to record the outcome. In the planner flow the child items are blocked-by this step, so
nothing downstream runs until you close it; in the linear flow this is the entry gate the write-code step
waits behind.

1. `lc show STEP` for the spec artifact; open it with `cmux markdown open <path>`.
2. Walk the human through the decisions, the decomposition, and the risks - not the prose. Answer
   their questions about any detail; surface the soft spots rather than defending the plan.
3. On their verdict:
   - Approve -> `lc done STEP approved` (closes the gate; unblocks the children in the planner
     flow, advances to write-code in the linear flow).
   - Changes -> `lc done STEP changes` (-> draft-spec) with a note saying exactly what to revise.

The human makes the call; you assist and do the bookkeeping. No emdashes.
