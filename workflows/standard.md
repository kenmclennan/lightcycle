# Standard

Spec -> code -> review -> open PR -> watch CI -> human merge, with a develop/plan
front end and a conflict-resolution branch. This is the default workflow; the
`nodes` block names the step file that performs each stage (omitted where the
stage and file names already match).

entry: build

nodes:
  build   coder
  review  reviewer
  audit   auditor

edges:
  build        done       review
  review       done       open-pr
  review       rejected   build
  open-pr      done       watch-pr
  open-pr      conflicted resolve
  watch-pr     done       ready-merge
  watch-pr     ci-failed  build
  ready-merge  merged     cleanup
  ready-merge  changes    build
  ready-merge  conflicted resolve
  ready-merge  gave-up    conflict-review
  resolve      resolved   open-pr
  resolve      escalate   conflict-review
  develop      drafted    review-plan
  review-plan  changes    develop

hooks:
  pr_merge              ready-merge  merged
  pr_close              ready-merge  abandoned
  pr_rework             ready-merge  changes
  pr_conflict           ready-merge  conflicted
  pr_conflict_cap       ready-merge  3
  pr_conflict_escalate  ready-merge  gave-up
  epic_close            audit
  retro_cadence         audit

signals:
  review       review_rounds    rejected
  review       resets           rejected
  open-pr      conflicts        ~conflict
  watch-pr     resets           ci-failed
  ready-merge  resets           changes
  resolve      resolve_attempts escalate
  review-plan  resets           changes
