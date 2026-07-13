# Spec

A brief from co-design becomes a formal spec, committed on an isolated branch of the specs repo,
ready for review (B2) and the PR (B3). Distinct from the code workflow: its worktrees come from
the specs repo (where `specs-remote` points), not a project repo. `open-pr` and `await-merge` are
reused from the code workflow; the PR monitor drives the outcome - a merged PR closes the item
`spec-merged` and files a single code item (carrying the merged spec and repo) into the code
workflow at `write-code` (C1: one item, no decomposition; C2 turns this into a decomposing
planner), a closed-unmerged PR closes it `abandoned`, and an `@lc` mention routes back to
`spec-writer` for rework.

entry: spec-writer

workspace: specs

requires: brief repo

edges:
  spec-writer  done         open-pr
  open-pr      done         await-merge
  await-merge  changes      spec-writer

hooks:
  pr_merge     await-merge  spec-merged
  pr_close     await-merge  abandoned
  pr_feedback  await-merge  handle-feedback
  mention_token  await-merge  @lc
  files_item   spec-merged  standard  write-code
