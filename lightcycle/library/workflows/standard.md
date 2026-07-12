# Standard

Spec -> code -> open PR -> watch CI -> review -> human merge, with a draft/review-spec
front end and a conflict-resolution branch. This is the default workflow. Each step name
is an action; the step name and its markdown file are the same word.

entry: review-spec

requires: repo

edges:
  write-code       done        open-pr
  open-pr          done        watch-ci
  open-pr          conflicted  resolve-conflict
  watch-ci         done        review-code
  watch-ci         ci-failed   write-code
  review-code      done        await-merge
  review-code      rejected    write-code
  await-merge      merged      cleanup
  await-merge      changes     write-code
  await-merge      conflicted  resolve-conflict
  await-merge      gave-up     review-conflict
  resolve-conflict resolved    open-pr
  resolve-conflict escalate    review-conflict
  draft-spec       drafted     review-spec
  review-spec      changes     draft-spec
  review-spec      approved    write-code
  audit            findings    review-findings
  audit            clean

hooks:
  pr_merge              await-merge  merged
  pr_close              await-merge  abandoned
  pr_feedback           await-merge  handle-feedback
  pr_conflict           await-merge  conflicted
  pr_conflict_cap       await-merge  3
  pr_conflict_escalate  await-merge  gave-up
  ci_failed_cap         watch-ci     ci-failed  3  review-ci
  mention_token         await-merge  @lc
  review_bot_allowlist  await-merge  copilot-pull-request-reviewer[bot]
  retro_cadence         audit

signals:
  review-code       review_rounds     rejected
  review-code       resets            rejected
  open-pr           conflicts         ~conflict
  watch-ci          resets            ci-failed
  await-merge       resets            changes
  resolve-conflict  resolve_attempts  escalate
  review-spec       resets            changes
