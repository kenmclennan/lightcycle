# Spec-driven

One item, one id, spanning the whole arc: a brief from co-design becomes a formal spec on a spec
PR, and once that PR merges the same item continues into the code build - write the code, open a
code PR, watch CI, review, human merge. There is no workflow flip: the spec phase and the code
phase are two positions of one workflow. `open-pr` and `await-merge` each appear twice (once per
PR); the spec-phase steps take their worktree from the specs repo (`specs-remote`), the code phase
from the project repo. The human review gate is the spec PR itself - no separate inline
draft/review step.

entry: spec-writer

requires: brief repo

workspace:
  spec-writer       specs
  spec-open-pr      specs
  spec-await-merge  specs

nodes:
  spec-open-pr      open-pr
  spec-await-merge  await-merge
  code-open-pr      open-pr
  code-await-merge  await-merge

edges:
  spec-writer       done         spec-open-pr
  spec-open-pr      done         spec-await-merge
  spec-await-merge  changes      spec-writer
  spec-await-merge  spec-merged  write-code
  write-code        done         code-open-pr
  code-open-pr      done         watch-ci
  code-open-pr      conflicted   resolve-conflict
  watch-ci          done         review-code
  watch-ci          ci-failed    write-code
  review-code       done         code-await-merge
  review-code       rejected     write-code
  code-await-merge  merged       cleanup
  code-await-merge  changes      write-code
  code-await-merge  conflicted   resolve-conflict
  code-await-merge  gave-up      review-conflict
  resolve-conflict  resolved     code-open-pr
  resolve-conflict  escalate     review-conflict
  audit             findings     review-findings
  audit             clean

hooks:
  pr_merge              spec-await-merge  spec-merged
  pr_merge              code-await-merge  merged
  pr_close              spec-await-merge  abandoned
  pr_close              code-await-merge  abandoned
  pr_feedback           spec-await-merge  handle-feedback
  pr_feedback           code-await-merge  handle-feedback
  pr_conflict           code-await-merge  conflicted
  pr_conflict_cap       code-await-merge  3
  pr_conflict_escalate  code-await-merge  gave-up
  ci_failed_cap         watch-ci          ci-failed  3  review-ci
  mention_token         spec-await-merge  @lc
  mention_token         code-await-merge  @lc
  review_bot_allowlist  code-await-merge  copilot-pull-request-reviewer[bot]
  retro_cadence         audit

signals:
  spec-await-merge  resets            changes
  review-code       review_rounds     rejected
  review-code       resets            rejected
  code-open-pr      conflicts         ~conflict
  watch-ci          resets            ci-failed
  code-await-merge  resets            changes
  resolve-conflict  resolve_attempts  escalate
