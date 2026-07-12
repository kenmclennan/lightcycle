# Spec

A brief from co-design becomes a formal spec, committed on an isolated branch of the specs repo,
ready for review (B2) and the PR (B3). Distinct from the code workflow: its worktrees come from
the specs repo (where `specs-remote` points), not a project repo.

entry: spec-writer

workspace: specs

requires: brief

edges:
  spec-writer  done
