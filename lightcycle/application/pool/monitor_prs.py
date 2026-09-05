from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.flow.unblock_step import UnblockInput, UnblockStepUseCase
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.domain.runs import RunState
from lightcycle.domain.work import State
from lightcycle.ports.github import ReadFailure

LC_MARKER = "<!-- lc -->"

CI_PENDING_LABEL = "ci-pending"
CI_RELEASED_PREFIX = "ci-released:"
CI_RELEASE_CAP = 3



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


def _epoch(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class MonitorPrsResponse:
    merged: List[str]
    abandoned: List[str] = field(default_factory=list)
    reworked: List[str] = field(default_factory=list)
    conflicted: List[str] = field(default_factory=list)
    ci_released: List[str] = field(default_factory=list)


class MonitorPrsUseCase:
    def __init__(self, store, github, worktrees, flow_service, complete=None):
        self._store = store
        self._github = github
        self._worktrees = worktrees
        self._flow_service = flow_service
        self._complete = complete

    def _flow_for(self, node):
        return self._flow_service.flow_for(node)

    def _run_of(self, node):
        phase = self._flow_for(node).phase_of(getattr(node, "step", None))
        return self._store.current_run(node.item, phase)

    def _pr_value(self, node, item_id):
        phase = self._flow_for(node).phase_of(getattr(node, "step", None))
        run = self._store.current_run(item_id, phase)
        return run.pr if run else None

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

    def _note_gh_read_failure(self, step_id, failure):
        self._store.note_condition(
            step_id,
            "gh read failed while checking outstanding feedback (exit %d): %s"
            % (failure.returncode, failure.stderr),
        )

    def _unauthorized_drops(self, pr_value, dropped):
        top_level = self._github.comments_since(pr_value, 0.0)
        inline = self._github.pull_comments(pr_value, 0.0)
        reviews = self._github.reviews(pr_value, 0.0)
        failure = next(
            (r for r in (top_level, inline, reviews) if isinstance(r, ReadFailure)), None
        )
        if failure is not None:
            return dropped, True
        marked_bodies = [c.body for c in list(top_level) + list(inline) if LC_MARKER in c.body]
        marked_bodies += [r.body for r in reviews if LC_MARKER in r.body]
        unauthorized = {f for f in dropped if not any(f in body for body in marked_bodies)}
        return unauthorized, False

    def _check_content_pin(self, item, pr_value, phase):
        run = self._store.current_run(item.id, phase)
        if run is None:
            return
        head = self._github.head_sha(pr_value)
        if run.pr != pr_value:
            self._store.set_run_field(run.id, pr=pr_value, content_pin=head)
            return
        pin = run.content_pin
        if pin == head:
            return
        old_files = self._github.changed_files(pr_value, pin)
        new_files = self._github.changed_files(pr_value, head)
        if isinstance(old_files, ReadFailure) or isinstance(new_files, ReadFailure):
            return
        dropped = old_files - new_files
        if dropped:
            unauthorized, lookup_failed = self._unauthorized_drops(pr_value, dropped)
            if lookup_failed:
                reported = dropped
                thread_note = (
                    " Could not read the PR's review thread to check whether this was ordered."
                )
            else:
                reported = unauthorized
                thread_note = ""
            if reported:
                base_note = (
                    "PR head moved from %s to %s and dropped: %s - a previously-reviewed change "
                    "may have been lost; verify before merging.%s"
                    % (pin, head, ", ".join(sorted(reported)), thread_note)
                )
                step = self._active_step_any(item.id)
                if step is not None and step.state != State.IN_PROGRESS:
                    decision = (
                        "confirm whether the drop of %s was ordered by review, or should be "
                        "restored" % ", ".join(sorted(reported))
                    )
                    observation = (
                        "PR head moved from %s to %s and dropped: %s.%s A file dropped between "
                        "review rounds is commonly review-code ordering its removal in feedback "
                        "and write-code carrying it out - checked the PR's review thread for "
                        "that instruction and did not find one accounting for %s."
                        % (pin, head, ", ".join(sorted(reported)), thread_note,
                           ", ".join(sorted(reported)))
                    )
                    ParkStepUseCase(self._store).execute(
                        ParkInput(step=step.id, observation=observation, decision=decision)
                    )
                else:
                    target = step or self._latest_step(item.id)
                    if target is not None:
                        self._store.note_condition(target.id, base_note)
        self._store.set_run_field(run.id, content_pin=head)

    def _release_ci_pending(self):
        released = []
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE:
                continue
            if step.role != "human":
                continue
            labels = self._store.labels_of(step.id)
            if CI_PENDING_LABEL not in labels:
                continue
            run = self._run_of(step)
            pr_value = run.pr if run else None
            if not pr_value:
                continue
            sha = self._github.head_sha(pr_value)
            if not sha:
                continue
            pending = self._github.ci_pending(pr_value, sha)
            if isinstance(pending, ReadFailure) or pending:
                continue
            released_so_far = sum(1 for l in labels if l.startswith(CI_RELEASED_PREFIX))
            if released_so_far >= CI_RELEASE_CAP:
                self._store.note_condition(
                    step.id,
                    "CI concluded but the automatic release cap (%d) was already reached; "
                    "a human must resume this step." % CI_RELEASE_CAP,
                )
                continue
            UnblockStepUseCase(self._store, self._flow_service).execute(
                UnblockInput(step=step.id)
            )
            self._store.label_remove(step.id, CI_PENDING_LABEL)
            self._store.label_add(
                step.id, "%s%d" % (CI_RELEASED_PREFIX, released_so_far + 1)
            )
            released.append(step.parent)
        return released

    def _latest_step(self, item_id):
        steps = sorted(self._store.children(item_id), key=lambda s: s.id)
        return steps[-1] if steps else None

    def _close_run(self, run, state):
        self._store.close_run(run.id, state)
        if self._worktrees is not None:
            self._worktrees.release_run(run)

    def execute(self) -> MonitorPrsResponse:
        merged, abandoned, reworked, conflicted = [], [], [], []
        close = CloseItemUseCase(self._store, self._worktrees)
        for item in self._store.all_nodes():
            if item.type != "item":
                continue
            if not any(r.pr for r in self._store.open_runs_of(item.id)):
                continue
            flow = self._flow_for(item)
            resolved = False
            for stage in flow.merge_stages():
                phase = flow.phase_of(stage)
                run = self._store.current_run(item.id, phase)
                pr_value = run.pr if run else None
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
                        self._close_run(run, RunState.MERGED)
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
                        self._close_run(run, RunState.ABANDONED)
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
            run = self._run_of(step)
            pr_value = run.pr if run else None
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
                    spawned_through = _epoch(run.comments_dispatched_through) if run else 0.0
                    if not open_now and newest > spawned_through:
                        role = flow.owner_of(feedback_step)
                        title = self._store.get_node(step.parent).title
                        tid = self._store.create_step(
                            "%s: %s" % (feedback_step, title), step=feedback_step,
                            role=role, parent=step.parent,
                        )
                        self._store.set_watched_step(tid, step.id)
                        if run is not None:
                            self._store.set_run_field(
                                run.id, comments_dispatched_through=str(newest)
                            )
                        reworked.append(step.parent)
            if not advanced and conflict_outcome and self._github.is_conflicted(pr_value):
                prior = sum(1 for t in self._store.steps_at_step(step.step)
                            if t.parent == step.parent
                            and t.state == State.DONE and t.outcome == conflict_outcome)
                outcome = flow.pr_conflict_transition(step.step, conflict_outcome, prior)
                self._complete.execute(CompleteInput(step=step.id, outcome=outcome))
                conflicted.append(step.parent)
        ci_released = self._release_ci_pending()
        return MonitorPrsResponse(
            merged=merged, abandoned=abandoned, reworked=reworked, conflicted=conflicted,
            ci_released=ci_released,
        )

    def _outstanding_feedback(self, step, pr, flow):
        since = self._github.last_push_time(pr)
        if isinstance(since, ReadFailure):
            self._note_gh_read_failure(step.id, since)
            return []
        top_level = self._github.comments_since(pr, since)
        inline = self._github.pull_comments(pr, since)
        reviews = self._github.reviews(pr, since)
        failure = next(
            (r for r in (top_level, inline, reviews) if isinstance(r, ReadFailure)), None
        )
        if failure is not None:
            self._note_gh_read_failure(step.id, failure)
            return []

        allowlist = flow.review_bot_allowlist(step.step)
        items = [c for c in _outstanding_threads(inline) if _eligible(c.author, allowlist)]
        items += [
            r for r in _outstanding_reviews(reviews, top_level + inline) if r.author in allowlist
        ]

        mention_token = flow.mention_token(step.step)
        if mention_token:
            feedback_run = self._run_of(step)
            watermark = _epoch(feedback_run.comments_handled_through) if feedback_run else 0.0
            items += [
                c for c in top_level
                if LC_MARKER not in c.body and not _is_bot(c.author)
                and mention_token in c.body and c.created_at > watermark
            ]

        return items
