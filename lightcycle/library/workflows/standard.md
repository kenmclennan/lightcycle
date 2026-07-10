# Standard

Spec -> code -> review -> open PR -> watch CI -> human merge, with a draft/review-spec
front end and a conflict-resolution branch. This is the default workflow. Each step name
is an action; the step name and its markdown file are the same word.

entry: review-spec

edges:
  write-code       done        review-code
  review-code      done        open-pr
  review-code      rejected    write-code
  open-pr          done        watch-ci
  open-pr          conflicted  resolve-conflict
  watch-ci         done        await-merge
  watch-ci         ci-failed   write-code
  await-merge      merged      cleanup
  await-merge      changes     write-code
  await-merge      conflicted  resolve-conflict
  await-merge      gave-up     review-conflict
  resolve-conflict resolved    open-pr
  resolve-conflict escalate    review-conflict
  draft-spec       drafted     review-spec
  review-spec      changes     draft-spec
  review-spec      approved    write-code

hooks:
  pr_merge              await-merge  merged
  pr_close              await-merge  abandoned
  pr_feedback           await-merge  handle-feedback
  pr_conflict           await-merge  conflicted
  pr_conflict_cap       await-merge  3
  pr_conflict_escalate  await-merge  gave-up
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
