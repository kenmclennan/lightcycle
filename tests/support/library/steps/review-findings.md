# Review-findings (you + driver)

The periodic retro escalated something: a defect in the process or setup, not a verdict on
anyone's delivered work. You decide what, if anything, happens next; the driver runs this skill to
record it.

1. `lc show STEP` - the forwarded note carries the audit's digest and its recommendation (stamped
   "from audit (findings): ..."); the same text also lives as the `findings` artifact on the audit
   step that spawned this one, if you want the durable record.
2. Discuss it with the human: does the finding hold up, and is the recommendation worth acting on.
3. `lc done STEP reviewed` either way - reviewing it is the acknowledgement. This step creates no
   work itself; if the human wants to act on it, they run `lc new` separately.

No emdashes.
