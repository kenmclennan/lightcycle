---
step: develop
produces:
  spec: required
routes:
  drafted: review-plan
---

# Develop (you + driver)

A seed - a raw idea - needs shaping into a spec before any work can start. You do this WITH the
human; the driver runs this skill. The driver mechanizes a shape the human decides; it does not
invent intent.

1. `tg show TASK` to read the seed. Re-read the relevant sibling specs and code for convention
   before drafting - do not produce from memory.
2. Co-design with the human, one decision at a time: brainstorm, then settle what we chose, what
   we rejected, and why. Foundations before detail. The human sets the pace; do not race ahead.
3. Write the spec. It needs two things: clarity for the agents that build and review it, and
   something the human can review. the-grid imposes NO fixed shape or contents - use the best
   spec-writing approach available to you. Hyphens not emdashes; format with prettier
   (`npx prettier --write`). If the work is big, the spec may break into phases, each with a
   review checkpoint - one story per phase, from the single spec.
4. `tg link TASK spec <path>` to attach it.
5. `tg done TASK drafted` (-> review-plan), which surfaces the spec in the human's inbox to review.

No emdashes.
