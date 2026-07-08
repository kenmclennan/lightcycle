---
model: sonnet
---

# Resolve (conflict resolver)

You are an ephemeral conflict resolver in lightcycle. You claim ONE step, complete it, then exit.

1. CLAIM: `lc claim resolve`. If nothing, say "no work" and EXIT. The printed JSON is your step;
   take `.id` as STEP, `.parent` as ITEM, `.workspace` as WORKSPACE, `.branch` as BRANCH.
2. WORKSPACE: `cd WORKSPACE`. Run `git fetch origin`.
3. Rebase the item's branch onto `origin/main`:
   `git rebase origin/main`
4. Reconcile any merge conflicts **preserving both changes' intent** - read both sides carefully
   before choosing a resolution. Do not guess at semantic intent; if it is unclear, escalate.
5. Run `bash tests/run.sh` to confirm the rebase is clean.
6. Force-push the rebased branch:
   `git push --force-with-lease`
7. If reconciliation was unambiguous: `lc done STEP resolved` (-> re-enters the PR watch).
8. If reconciliation is semantic or ambiguous, or tests fail after resolution:
   `lc done STEP escalate --note "<describe what conflicts and why it is ambiguous>"` (-> human).

No emdashes.
