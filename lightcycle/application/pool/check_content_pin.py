import json

from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.pool.pr_lookups import (
    active_step_any,
    active_step_in_phase,
    latest_step,
)
from lightcycle.application.pool.stack_reads import read_stack
from lightcycle.config import ConfigError
from lightcycle.domain.feedback import LC_MARKER, parse_decision, parse_decision_sha
from lightcycle.domain.pool import stack_shape
from lightcycle.domain.work import State
from lightcycle.ports.github import NotYetRead, ReadFailure


class CheckContentPinUseCase:
    def __init__(self, store, github, flow_service, *, trusted_authors):
        self._store = store
        self._trusted_authors = trusted_authors
        self._github = github
        self._flow_service = flow_service

    def _step_for_phase(self, item_id, phase):
        step = active_step_in_phase(self._store, self._flow_service, item_id, phase)
        return step or active_step_any(self._store, item_id)

    def _unauthorized_drops(self, pr_value, dropped, pin):
        top_level = self._github.comments_since(pr_value, 0.0)
        inline = self._github.pull_comments(pr_value, 0.0)
        reviews = self._github.reviews(pr_value, 0.0)
        failure = next(
            (r for r in (top_level, inline, reviews) if isinstance(r, ReadFailure)), None
        )
        if failure is not None:
            return dropped, True, False
        try:
            trusted = {t.casefold() for t in self._trusted_authors()}
        except ConfigError:
            return dropped, True, False
        authorized = set()
        round_ordered = False
        for c in list(top_level) + list(inline):
            if c.author.casefold() not in trusted or LC_MARKER not in c.body:
                continue
            if parse_decision(c.body) != "rework":
                continue
            if c.path:
                authorized.add(c.path)
            elif parse_decision_sha(c.body) == pin:
                round_ordered = True

        if round_ordered:
            return set(), False, True
        unauthorized = {f for f in dropped if f not in authorized}
        return unauthorized, False, False

    def execute(self, item, pr_value, phase):
        run = self._store.current_run(item.id, phase)
        if run is None:
            return
        if run.stack:
            self._execute_stacked(item, run, phase)
            return
        head = self._github.head_sha(pr_value)
        if isinstance(head, ReadFailure):
            return
        if run.pr != pr_value or run.content_pin is None:
            self._store.record_pr_pin(run.id, pr_value, head)
            return
        pin = run.content_pin
        if pin == head:
            return
        if self._review_move(item, pr_value, phase, pin, head, ""):
            self._store.set_content_pin(run.id, head)

    def _decode_pins(self, text):
        try:
            value = json.loads(text) if text else None
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _execute_stacked(self, item, run, phase):
        read = read_stack(self._github, run.stack)
        if not read.layers:
            return
        pins = self._decode_pins(run.content_pin)
        updated = dict(pins)
        total = len(read.layers)
        for position, layer in enumerate(read.layers, start=1):
            if layer.state != "open":
                continue
            head = self._github.head_sha(layer.url)
            if isinstance(head, ReadFailure):
                continue
            pin = pins.get(layer.url)
            if pin is None:
                updated[layer.url] = head
                continue
            if pin == head:
                continue
            fresh = self._github.diff_signature(layer.url, head)
            if isinstance(fresh, NotYetRead):
                continue
            prior = self._github.diff_signature(layer.url, pin)
            if isinstance(fresh, str) and fresh == prior:
                updated[layer.url] = head
                continue
            prefix = "%s: " % stack_shape.label(position, total, layer.url)
            retained = self._retained_by_others(read.layers, layer.url)
            if self._review_move(item, layer.url, phase, pin, head, prefix, retained):
                updated[layer.url] = head
        encoded = json.dumps(updated, sort_keys=True)
        if updated and encoded != run.content_pin:
            self._store.set_content_pin(run.id, encoded)

    def _retained_by_others(self, layers, own_url):
        def read_others():
            files = set()
            for other in layers:
                if other.url == own_url or other.state != "open":
                    continue
                other_head = self._github.head_sha(other.url)
                if isinstance(other_head, ReadFailure):
                    return None
                other_files = self._github.changed_files(other.url, other_head)
                if isinstance(other_files, ReadFailure):
                    return None
                files |= set(other_files)
            return files

        return read_others

    def _review_move(self, item, pr_value, phase, pin, head, prefix, retained=None):
        old_files = self._github.changed_files(pr_value, pin)
        new_files = self._github.changed_files(pr_value, head)
        if isinstance(old_files, ReadFailure) or isinstance(new_files, ReadFailure):
            return False
        dropped = old_files - new_files
        if dropped and retained is not None:
            carried = retained()
            if carried is None:
                return False
            dropped = dropped - carried
        if dropped:
            unauthorized, lookup_failed, round_ordered = self._unauthorized_drops(
                pr_value, dropped, pin
            )
            if round_ordered:
                target = self._step_for_phase(item.id, phase) or latest_step(
                    self._store, item.id
                )
                if target is not None:
                    self._store.note_condition(
                        target.id,
                        "%sPR head moved from %s to %s and dropped: %s - ordered by the rework "
                        "decision recorded against %s."
                        % (prefix, pin, head, ", ".join(sorted(dropped)), pin),
                    )
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
                    "%sPR head moved from %s to %s and dropped: %s - a previously-reviewed change "
                    "may have been lost; verify before merging.%s"
                    % (prefix, pin, head, ", ".join(sorted(reported)), thread_note)
                )
                step = self._step_for_phase(item.id, phase)
                if step is not None and step.state != State.RUNNING:
                    decision = (
                        "confirm whether the drop of %s was ordered by review, or should be "
                        "restored" % ", ".join(sorted(reported))
                    )
                    observation = (
                        "%sPR head moved from %s to %s and dropped: %s.%s A file dropped between "
                        "review rounds is commonly review-code ordering its removal in feedback "
                        "and write-code carrying it out - checked the PR's review thread for "
                        "that instruction and did not find one accounting for %s."
                        % (prefix, pin, head, ", ".join(sorted(reported)), thread_note,
                           ", ".join(sorted(reported)))
                    )
                    ParkStepUseCase(self._store).execute(
                        ParkInput(step=step.id, observation=observation, decision=decision)
                    )
                else:
                    target = step or latest_step(self._store, item.id)
                    if target is not None:
                        self._store.note_condition(target.id, base_note)
        return True
