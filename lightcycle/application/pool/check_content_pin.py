from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.pool.pr_lookups import active_step_any, latest_step
from lightcycle.domain.feedback import LC_MARKER
from lightcycle.domain.work import State
from lightcycle.ports.github import ReadFailure


class CheckContentPinUseCase:
    def __init__(self, store, github):
        self._store = store
        self._github = github

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

    def execute(self, item, pr_value, phase):
        run = self._store.current_run(item.id, phase)
        if run is None:
            return
        head = self._github.head_sha(pr_value)
        if isinstance(head, ReadFailure):
            return
        if run.pr != pr_value:
            self._store.record_pr_pin(run.id, pr_value, head)
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
                step = active_step_any(self._store, item.id)
                if step is not None and step.state != State.RUNNING:
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
                    target = step or latest_step(self._store, item.id)
                    if target is not None:
                        self._store.note_condition(target.id, base_note)
        self._store.set_content_pin(run.id, head)
