from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.domain.work import Item, State
from lightcycle.ports.github import ReadFailure

LC_MARKER = "<!-- lc -->"
_WATERMARK_ARTIFACT = "feedback-watermark"
_SPAWN_MARK_ARTIFACT = "feedback-spawned-through"
_CONTENT_PIN_ARTIFACT = "content-pin"
_CONTENT_PIN_PR_ARTIFACT = "content-pin-pr"


def _is_bot(author):
    return "[bot]" in author


def _eligible(author, allowlist):
    return not _is_bot(author) or author in allowlist


def _thread_key(comment):
    return comment.in_reply_to_id or comment.id


def _outstanding_threads(comments):
    marked_threads = {_thread_key(c) for c in comments if LC_MARKER in c.body}
    latest = {}
    for c in sorted(comments, key=lambda c: c.created_at):
        if LC_MARKER in c.body:
            continue
        key = _thread_key(c)
        if key is None or key in marked_threads:
            continue
        latest[key] = c
    return list(latest.values())


def _review_has_signal(review):
    if review.state == "CHANGES_REQUESTED":
        return True
    if review.state == "COMMENTED":
        return bool(review.body.strip())
    return False


def _outstanding_reviews(reviews, comments):
    marked_at = sorted(c.created_at for c in comments if LC_MARKER in c.body)
    outstanding = []
    for r in reviews:
        if not _review_has_signal(r):
            continue
        if LC_MARKER in r.body:
            continue
        if any(ts > r.created_at for ts in marked_at):
            continue
        outstanding.append(r)
    return outstanding


def _watermark(artifacts):
    watermark = next((a for a in artifacts if a.type == _WATERMARK_ARTIFACT), None)
    if watermark is None:
        return 0.0
    try:
        return float(watermark.value)
    except (TypeError, ValueError):
        return 0.0


def _spawned_through(artifacts):
    a = next((a for a in artifacts if a.type == _SPAWN_MARK_ARTIFACT), None)
    if a is None:
        return 0.0
    try:
        return float(a.value)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class MonitorPrsResponse:
    merged: List[str]
    abandoned: List[str] = field(default_factory=list)
    reworked: List[str] = field(default_factory=list)
    conflicted: List[str] = field(default_factory=list)


class MonitorPrsUseCase:
    def __init__(self, store, github, worktrees, flow_service, complete=None):
        self._store = store
        self._github = github
        self._worktrees = worktrees
        self._flow_service = flow_service
        self._complete = complete

    def _flow_for(self, node):
        return self._flow_service.flow_for(node)

    def _pr_value(self, node, item_id):
        phase = self._flow_service.phase_for(node)
        artifacts = tuple(self._store.item_artifacts(item_id))
        return Item(item_id, artifacts).artifact_of("pr", label=phase)

    def _active_step_at(self, item_id, stage):
        for child in self._store.children(item_id):
            if child.type == "step" and child.state != State.DONE and child.step == stage:
                return child
        return None

    def _active_step_any(self, item_id):
        for child in self._store.children(item_id):
            if child.type == "step" and child.state != State.DONE:
                return child
        return None

    def _note_gh_read_failure(self, item_id, failure):
        self._store.note(
            item_id,
            "gh read failed while checking outstanding feedback (exit %d): %s"
            % (failure.returncode, failure.stderr),
        )

    def _check_content_pin(self, item, pr_value, phase):
        head = self._github.head_sha(pr_value)
        artifacts = tuple(self._store.item_artifacts(item.id))
        pinned_pr = next(
            (a.value for a in artifacts
             if a.type == _CONTENT_PIN_PR_ARTIFACT and a.label == phase),
            None,
        )
        if pinned_pr != pr_value:
            self._store.replace_artifact(
                item.id, _CONTENT_PIN_PR_ARTIFACT, pr_value, label=phase, internal=True
            )
            self._store.replace_artifact(
                item.id, _CONTENT_PIN_ARTIFACT, head, label=phase, internal=True
            )
            return
        pin = next(
            (a.value for a in artifacts
             if a.type == _CONTENT_PIN_ARTIFACT and a.label == phase),
            None,
        )
        if pin == head:
            return
        old_files = self._github.changed_files(pr_value, pin)
        new_files = self._github.changed_files(pr_value, head)
        if isinstance(old_files, ReadFailure) or isinstance(new_files, ReadFailure):
            return
        dropped = old_files - new_files
        if dropped:
            base_note = (
                "PR head moved from %s to %s and dropped: %s - a previously-reviewed change "
                "may have been lost; verify before merging."
                % (pin, head, ", ".join(sorted(dropped)))
            )
            step = self._active_step_any(item.id)
            if step is not None and step.state != State.IN_PROGRESS:
                decision = (
                    "confirm whether the drop of %s was ordered by review, or should be "
                    "restored" % ", ".join(sorted(dropped))
                )
                observation = (
                    "PR head moved from %s to %s and dropped: %s. A file dropped between "
                    "review rounds is commonly review-code ordering its removal in feedback "
                    "and write-code carrying it out - check the PR's review thread for that "
                    "instruction before treating this as lost work."
                    % (pin, head, ", ".join(sorted(dropped)))
                )
                ParkStepUseCase(self._store).execute(
                    ParkInput(step=step.id, observation=observation, decision=decision)
                )
            else:
                self._store.note(item.id, base_note)
        self._store.replace_artifact(
            item.id, _CONTENT_PIN_ARTIFACT, head, label=phase, internal=True
        )

    def execute(self) -> MonitorPrsResponse:
        merged, abandoned, reworked, conflicted = [], [], [], []
        close = CloseItemUseCase(self._store, self._worktrees)
        for item in self._store.all_nodes():
            if item.type != "item":
                continue
            artifacts = tuple(self._store.item_artifacts(item.id))
            if not any(a.type == "pr" for a in artifacts):
                continue
            flow = self._flow_for(item)
            resolved = False
            for stage in flow.merge_stages():
                phase = flow.phase_of(stage)
                pr_value = Item(item.id, artifacts).artifact_of("pr", label=phase)
                if pr_value is None:
                    continue
                self._check_content_pin(item, pr_value, phase)
                merge_outcome = flow.merge_outcome(stage)
                close_outcome = flow.close_outcome(stage)
                if merge_outcome and self._github.is_merged(pr_value):
                    nxt = flow.next(stage, merge_outcome)
                    if nxt and nxt.to_step and not nxt.to_terminal:
                        step = self._active_step_at(item.id, stage)
                        if step is None:
                            continue
                        if flow.phase_of(stage) != flow.phase_of(nxt.to_step):
                            self._worktrees.remove(item.id)
                        self._complete.execute(CompleteInput(step=step.id, outcome=merge_outcome))
                    else:
                        close.execute(CloseItemInput(item=item.id, reason=merge_outcome))
                        resolved = True
                    merged.append(item.id)
                elif close_outcome and self._github.is_closed_unmerged(pr_value):
                    nxt = flow.next(stage, close_outcome)
                    if nxt and nxt.to_step and not nxt.to_terminal:
                        step = self._active_step_at(item.id, stage)
                        if step is None:
                            continue
                        if flow.phase_of(stage) != flow.phase_of(nxt.to_step):
                            self._worktrees.remove(item.id)
                        self._complete.execute(CompleteInput(step=step.id, outcome=close_outcome))
                    else:
                        close.execute(CloseItemInput(item=item.id, reason=close_outcome))
                        resolved = True
                    abandoned.append(item.id)
                if resolved:
                    break
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE:
                continue
            if not step.parent:
                continue
            flow = self._flow_for(step)
            feedback_step = flow.pr_feedback_step(step.step)
            conflict_outcome = flow.pr_conflict_outcome(step.step)
            if feedback_step is None and conflict_outcome is None:
                continue
            pr_value = self._pr_value(step, step.parent)
            if pr_value is None:
                continue
            advanced = False
            if feedback_step:
                outstanding = self._outstanding_feedback(step, pr_value, flow)
                if outstanding:
                    advanced = True
                    newest = max(o.created_at for o in outstanding)
                    open_now = any(
                        n.type == "step" and n.step == feedback_step and n.parent == step.parent
                        for n in self._store.all_nodes()
                    )
                    spawned_through = _spawned_through(self._store.item_artifacts(step.id))
                    if not open_now and newest > spawned_through:
                        role = flow.owner_of(feedback_step)
                        title = self._store.get_node(step.parent).title
                        tid = self._store.create_step(
                            "%s: %s" % (feedback_step, title), step=feedback_step,
                            role=role, parent=step.parent,
                        )
                        self._store.add_artifact(tid, "watched-step", step.id, internal=True)
                        self._store.replace_artifact(
                            step.id, _SPAWN_MARK_ARTIFACT, str(newest), internal=True
                        )
                        reworked.append(step.parent)
            if not advanced and conflict_outcome and self._github.is_conflicted(pr_value):
                prior = sum(1 for t in self._store.steps_at_step(step.step)
                            if t.parent == step.parent
                            and t.state == State.DONE and t.outcome == conflict_outcome)
                outcome = flow.pr_conflict_transition(step.step, conflict_outcome, prior)
                self._complete.execute(CompleteInput(step=step.id, outcome=outcome))
                conflicted.append(step.parent)
        return MonitorPrsResponse(
            merged=merged, abandoned=abandoned, reworked=reworked, conflicted=conflicted
        )

    def _outstanding_feedback(self, step, pr, flow):
        since = self._github.last_push_time(pr)
        if isinstance(since, ReadFailure):
            self._note_gh_read_failure(step.parent, since)
            return []
        top_level = self._github.comments_since(pr, since)
        inline = self._github.pull_comments(pr, since)
        reviews = self._github.reviews(pr, since)
        failure = next(
            (r for r in (top_level, inline, reviews) if isinstance(r, ReadFailure)), None
        )
        if failure is not None:
            self._note_gh_read_failure(step.parent, failure)
            return []

        allowlist = flow.review_bot_allowlist(step.step)
        items = [c for c in _outstanding_threads(inline) if _eligible(c.author, allowlist)]
        items += [
            r for r in _outstanding_reviews(reviews, top_level + inline) if r.author in allowlist
        ]

        mention_token = flow.mention_token(step.step)
        if mention_token:
            watermark = _watermark(self._store.item_artifacts(step.id))
            items += [
                c for c in top_level
                if LC_MARKER not in c.body and not _is_bot(c.author)
                and mention_token in c.body and c.created_at > watermark
            ]

        return items
