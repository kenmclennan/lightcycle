---
step: review-plan
routes:
  changes: develop
---

# Review-plan (you + driver)

A spec is waiting for review before work proceeds. You decide; the driver runs this skill to help
you and to record the outcome. In the planner flow the child stories are blocked-by this task, so
nothing downstream runs until you close it.

1. `tg show TASK` for the spec/plan artifact; open it with `cmux markdown open <path>`.
2. Walk the human through the decisions, the decomposition, and the risks - not the prose. Answer
   their questions about any detail; surface the soft spots rather than defending the plan.
3. On their verdict:
   - Approve -> `tg close TASK approved` (closes the gate; in the planner flow this unblocks the children).
   - Changes -> `tg done TASK changes` (-> develop) with a note saying exactly what to revise.

The human makes the call; you assist and do the bookkeeping. No emdashes.
