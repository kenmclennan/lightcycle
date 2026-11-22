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
from lightcycle.domain.work.timestamp import parse_timestamp
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

    def _review_rejected(self, item, phase):
        latest = None
        for step in self._store.children(item.id):
            if step.type != "step" or step.state != State.DONE or step.closed_at is None:
                continue
            if self._flow_service.phase_for(step) != phase:
                continue
            review = self._flow_service.flow_for(step).step_def(step.stage).review
            if review is None:
                continue
            at = parse_timestamp(step.closed_at)
            if latest is None or at >= latest[0]:
                latest = (at, step, review)
        if latest is None:
            return False
        outcome = latest[1].outcome
        return outcome is not None and outcome != latest[2]

    def _keep_paths(self, body):
        kept = set()
        for line in body.splitlines():
            if line.startswith("Keep:"):
                kept |= {p.strip() for p in line[len("Keep:"):].split(",") if p.strip()}
        return kept

    def _unauthorized_drops(self, pr_value, dropped, pin, review_rejected=False):
        top_level = self._github.comments_since(pr_value, 0.0)
        inline = self._github.pull_comments(pr_value, 0.0)
        reviews = self._github.reviews(pr_value, 0.0)
        failure = next(
            (r for r in (top_level, inline, reviews) if isinstance(r, ReadFailure)), None
        )
        if failure is not None:
            return dropped, True, False, set()
        try:
            trusted = {t.casefold() for t in self._trusted_authors()}
        except ConfigError:
            return dropped, True, False, set()
        authorized = set()
        round_ordered = False
        verdict_seen = False
        kept = set()
        for c in list(top_level) + list(inline):
            if c.author.casefold() not in trusted or LC_MARKER not in c.body:
                continue
            if (
                c.is_top_level
                and not c.path
                and parse_decision(c.body) is None
                and parse_decision_sha(c.body) == pin
            ):
                verdict_seen = True
                kept |= self._keep_paths(c.body)
            if parse_decision(c.body) != "rework":
                continue
            if c.path:
                authorized.add(c.path)
            elif parse_decision_sha(c.body) == pin:
                round_ordered = True

        if round_ordered:
            return set(), False, True, set()
        review_ordered = set()
        if review_rejected and verdict_seen:
            review_ordered = {f for f in dropped if f not in kept}
            authorized |= review_ordered
        unauthorized = {f for f in dropped if f not in authorized}
        return unauthorized, False, False, review_ordered

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
        heads = {}
        for position, layer in enumerate(read.layers, start=1):
            if layer.state != "open":
                continue
            head = self._github.head_sha(layer.url)
            if isinstance(head, ReadFailure):
                continue
            heads[layer.url] = head
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
            hold = self._hold_for(read.layers, layer.url, head, pins, updated)
            if self._review_move(item, layer.url, phase, pin, head, prefix, retained, hold):
                updated[layer.url] = head
        self._drop_ended_holds(read.layers, pins, updated, heads)
        encoded = json.dumps(updated, sort_keys=True)
        if updated and encoded != run.content_pin:
            self._store.set_content_pin(run.id, encoded)

    def _retained_by_others(self, layers, own_url):
        def read_others(unaccounted):
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
            if unaccounted - files:
                for other in layers:
                    if other.url == own_url or other.state != "merged":
                        continue
                    merged_files = self._github.pr_files(other.url)
                    if not isinstance(merged_files, ReadFailure):
                        files |= set(merged_files)
            return files

        return read_others

    def _hold_for(self, layers, own_url, head, pins, updated):
        key = "hold:%s" % own_url

        def hold(dropped):
            if pins.get(key) == head:
                return False
            for other in layers:
                if other.url == own_url or other.state != "open":
                    continue
                other_head = self._github.head_sha(other.url)
                if isinstance(other_head, str) and pins.get(other.url) == other_head:
                    updated[key] = head
                    return True
            return False

        return hold

    def _drop_ended_holds(self, layers, pins, updated, heads):
        open_urls = {layer.url for layer in layers if layer.state == "open"}
        for key in [k for k in updated if k.startswith("hold:")]:
            url = key[len("hold:"):]
            advanced = updated.get(url) != pins.get(url)
            moved_on = url in heads and heads[url] != updated[key]
            if url not in open_urls or advanced or moved_on:
                del updated[key]

    def _review_move(self, item, pr_value, phase, pin, head, prefix, retained=None, hold=None):
        old_files = self._github.changed_files(pr_value, pin)
        new_files = self._github.changed_files(pr_value, head)
        if isinstance(old_files, ReadFailure) or isinstance(new_files, ReadFailure):
            return False
        dropped = old_files - new_files
        if dropped:
            own = self._github.own_files(pr_value, pin)
            if isinstance(own, ReadFailure):
                return False
            dropped = dropped & own
        if dropped and retained is not None:
            carried = retained(dropped)
            if carried is None:
                return False
            dropped = dropped - carried
            if dropped and hold is not None and hold(dropped):
                return False
        if dropped:
            review_rejected = self._review_rejected(item, phase)
            unauthorized, lookup_failed, round_ordered, review_ordered = self._unauthorized_drops(
                pr_value, dropped, pin, review_rejected
            )
            if review_ordered:
                target = self._step_for_phase(item.id, phase) or latest_step(
                    self._store, item.id
                )
                if target is not None:
                    self._store.note_condition(
                        target.id,
                        "%sPR head moved from %s to %s and dropped: %s - ordered by the rejecting "
                        "review recorded against %s."
                        % (prefix, pin, head, ", ".join(sorted(review_ordered)), pin),
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
