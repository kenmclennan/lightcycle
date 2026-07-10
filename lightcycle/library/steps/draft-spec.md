---
produces:
  spec: required
---

# Draft-spec (you + driver)

A seed - a raw idea - needs shaping into a spec before any work can start. You do this WITH the
human; the driver runs this skill. The driver mechanizes a shape the human decides; it does not
invent intent.

1. `lc show STEP` to read the seed. Re-read the relevant sibling specs and code for convention
   before drafting - do not produce from memory.
2. Co-design with the human, one decision at a time: brainstorm, then settle what we chose, what
   we rejected, and why. Foundations before detail. The human sets the pace; do not race ahead.
3. Write the spec. It needs two things: clarity for the agents that build and review it, and
   something the human can review. lightcycle imposes NO fixed shape or contents - use the best
   spec-writing approach available to you. Hyphens not emdashes; format with prettier
   (`npx prettier --write`). If the work is big, the spec may break into phases, each with a
   review checkpoint - one item per phase, from the single spec.
   - **First draft**: run `lc specs-dir` to get the configured specs directory, then write the
     spec to `<specs-dir>/<name>.md`.
   - **Revise** (arriving here from review-plan's `changes` outcome): the item already carries a
     `spec` artifact. Edit that file at its existing path in place - never write a new
     `<name>.md` or add a second spec.
4. `lc attach STEP spec <path> --replace` to attach it. `--replace` swaps any existing `spec`
   artifact for the new one, so the item never ends up with two - harmless on a first draft (there
   is nothing to replace yet), required on a revise.
5. `lc done STEP drafted` (-> review-spec), which surfaces the spec in the human's inbox to review.

No emdashes.
