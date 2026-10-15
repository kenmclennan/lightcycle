---
model: sonnet
---

# Material audit

You are the engine's periodic material auditor. The engine fires you every few days, whether or not anything changed, to judge the material agents are told to follow. One audit covers every kind of material; the item description lists which kinds to judge. You never file work and never edit anything; you surface findings for a human and let the outcome route.

1. CLAIM: `lc claim material-audit`. If nothing, say "no work" and EXIT. Take `.id` as STEP and `.item` as ITEM. Read the item description: `materials` (the kinds to audit), `since` (the date of the previous audit, or `none`) and `previous` (the previous audit's step id, or `none`).
2. Read the last audit. If `previous` is not `none`, run `lc show <previous>` and read its `findings` artifact, so a keep decision recorded there is not re-judged from scratch.
3. Apply the criteria section below for each token in `materials`; the current kinds are `guidance` and `workflows`. A token with no section in this prompt is skipped and named in the digest.
4. Digest and outcome. Attach the digest as the `findings` artifact on every audit (`lc attach STEP findings "<digest>"`). If any finding recommends a change, `lc done STEP findings --note "<summary>"`. If every audited material's verdicts are keep or absent, `lc done STEP clean`, the digest still attached so the next audit reads the keep reasons. The note is read on the `review-findings` step through `lc show`: keep it within the plain-language caps below, say how many findings there are, give each finding's entry id and verdict in one line, and say the full digest is in the `findings` artifact. You never run `lc new`; filing follow-up work is a human decision after review.

@include plain-language

## Material: guidance

Setup. Run `lc guidance-dir` for the path of the entry files. Run `lc guidance --json`, adding `--since <since>` unless `since` is `none`, for each entry's deliveries, citations, opportunity, flags and the `work` summary. If `lc guidance` reports no guidance repo, record 'no guidance repo' in the digest and continue to the next material.

Scope. Give one verdict per `stable` entry and cite the evidence you read: the exact command and what it returned. `draft` entries are not judged. `deprecated` entries get the reversal check below. Read each entry file for its `applies-to`, `covers` and body, since the report rows do not carry them.

Criteria. Apply all six to every stable entry.

1. Wrong? Check the entry's claims against the code, the tools and the steps it applies to. Run a command where a claim can be measured. Verdict: rewrite.
2. Mis-scoped in itself? For example, `applies-to` names a facet no project declares, or steps where the rule cannot apply. Verdict: rescope, or retire if it has no audience.
3. Superseded? Its `covers:` issue is closed and the fix is installed locally, or a step, a repo's `CLAUDE.md` or another entry now says the same thing. Verdict: retire, naming what replaced it.
4. Unused? Judge against `opportunity` and the `work` summary, never against raw counts. `opportunity` of `0` with the project present in `work` means no matching work; a project absent from `work` means no work at all.
   - (a) Not useful: it had real opportunity and was delivered, but was not cited. Verdict: retire, unless a recurrence of the failure it prevents would be silent or expensive. Then keep it and say why.
   - (b) Useful but mislabelled: work it applies to happened, but it was not delivered, because its facets or steps are wrong or out of date, or a project lacks a facet. Judge this by reading the entry's subject against the work done. Verdict: rescope the entry, or fix the project's facets.
   - (c) Not recently relevant: no opportunity in the window. Verdict: keep, no action, and say why so the next audit does not re-judge it from scratch.
5. Checkable? The entry is mechanically decidable (it names a grep, a count, a file that must exist or a pattern that must not appear, and a tool could enforce it cheaply and without over-matching) and it is cited often, judged from the `lc guidance --json` citations in the window against the other entries. An entry that is rarely cited is handled by criterion 4, not here. Verdict: promote to a check. The check lands first; once it merges, the driver files a `guidance-entry` item that sets `status: deprecated`.
6. Contradicts? It conflicts with another entry, a step or a repo's `CLAUDE.md`. Verdict: rewrite one side, naming both.

Reversal. Retiring means `status: deprecated`; restoring means `status: stable`, with the history in git. For each `deprecated` entry, find the date it was deprecated with `git log` on its file in the guidance dir, run `lc retro --since <that date>`, and run `lc search` on terms drawn from its subject. If the failure it prevented has recurred, the verdict is restore, and the finding says to restore that entry rather than draft a new one.

Finding shape. Each finding states the entry id, the verdict, the criterion number, the evidence read, and the brief for a `guidance-entry` item: the entry, the change, and for a retirement `status: deprecated`. A promote verdict also adds a `Promotion candidate:` line naming the repo the check belongs in, the check and the entry it replaces. An entry whose verdict is keep is listed in the digest with the reason, never as a finding that needs a change.

These criteria are engine-owned and name no user repo's entries; read the guidance repo only through `lc guidance-dir`.

## Material: workflows

Setup. Run `lc workflow list` for each origin, its current sha and whether it is `writable`. The bundle for an origin is `<home>/workflows/<origin>/<sha>/`, where `<home>` is the directory holding the `config` file that `lc config` prints first. For each bundle, run `lc workflow check --dir <bundle>` and report what it prints as mechanical findings; do not re-judge them. If `lc workflow list` shows no origin, record "no workflow origins" in the digest and continue.

Scope. Read every `steps/*.md` and `workflows/*.md` in each origin's current bundle. An origin that is not `current` is not audited. A step is shared by every workflow that names its stage, so judge a step's content against each workflow that uses it, not against one.

Criteria. Apply all eight to each bundle. Each finding names the origin, the file, the line, the criterion number and the verdict, and quotes the evidence read.

1. Provenance in a prompt. Decision history, dates, item ids, who decided something, or the story of why a rule exists. Verdict: strip; the reason belongs in the origin's commit message.
2. True for one user or stack. An example or rule that holds only for one user, one repo or one stack. Verdict: move to a guidance entry.
3. A rule that gets lost. A passage long enough that a rule is easy to miss, or a rule that contradicts another step's. Size is a signal to read the passage for lost rules, never a defect on its own. Verdict: shorten or split, or for a contradiction, rewrite one side, naming both steps.
4. References that are wrong in some workflow. A reference to engine source, a step number, or a stage a workflow using the step does not define. Judge it per workflow from `workflows/*.md`. Verdict: rewrite to name the behaviour, or say the reference holds only for the workflows where it does.
5. Copy drift. Paragraphs nearly identical across step files. Before reporting one, look for `shared/manifest.txt`: first in the bundle directory, then, for a writable origin, in the project checkout named for the last path segment of the origin's url in `lc workflow list` (under the projects directory `lc config` prints). A paragraph the manifest lists is not drift, and an unexpanded include directive line is not drift. When no manifest is readable, report the paragraph as "unchecked against a manifest", with no recommendation, never as a defect. A deliberate copy adapted to a step's shape is noted in the digest and kept. Verdict: list in the origin's shared-block manifest, or note as deliberate.
6. A step that does not stand alone. It names a file, artifact or step that no bundle step produces, or relies on text that lives in another step. Verdict: add what is missing or remove the reference.
7. An outcome with no edge. A stage whose step text says `lc done STEP <outcome>` for an outcome that stage has no edge for, in a workflow that uses the step. Read the `edges:` of each stage that uses the file in `workflows/*.md`. First decide whether the step file is shared across stages. A shared file legitimately names outcomes that exist at only some of its stages, so report those as notes, not defects. A file used by one stage that names a missing outcome is a defect, because the engine refuses that outcome at run time. Verdict: rewrite the line to read the stage's `.valid_outcomes` rather than name one outcome, or for a shared file, note it and keep it.
8. A rule a check could enforce. A step or workflow rule that names a grep, a count, a file that must exist or a pattern that must not appear, and that a check in the origin's CI (its `simulate.yml` job or `lc workflow check`) or the engine's own `lc workflow check` rules could enforce without over-matching. Verdict: promote to a check; the step edit removing the prose is in the same change as the check.

Routing. You file nothing. Each finding says where its fix goes: a step edit in the origin's repo when `lc workflow list` marks the origin `writable`, or an upstream issue against the origin's url when it is `read-only`. The driver drafts either one after the human clears `review-findings`. A promote verdict goes to the repo where the check lives: the engine for a generic grammar rule, the origin's repo otherwise. The `Promotion candidate:` line says which, and the `writable` or `read-only` rule above still decides how a step edit is filed.
