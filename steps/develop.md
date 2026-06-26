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
3. Write the spec in the diagram-first review format: Summary, Scope (text + a diagram + caption),
   Decisions, Out of scope, Build tasks (diagram + table), Risks. Hyphens not emdashes. Format with
   prettier (`npx prettier --write`).
4. `tg link TASK spec <path>` to attach it.
5. `tg done TASK drafted` (-> review-plan), which surfaces the spec in the human's inbox to review.

The decisions and diagrams are what the human reviews; keep the narrative short. No emdashes.
