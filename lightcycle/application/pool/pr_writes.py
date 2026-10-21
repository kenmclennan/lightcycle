from dataclasses import dataclass
import threading
from typing import Optional

from lightcycle.ports.github import ReadFailure

RULE_TTL_SECONDS = 300

UPDATED = "updated"
UPDATE_FAILED = "update-failed"
NOT_REQUIRED = "not-required"
RULE_FAILED = "rule-failed"


@dataclass(frozen=True)
class WriteOutcome:
    kind: str
    failure: Optional[ReadFailure] = None


class PrWrites:
    def __init__(self, clock):
        self._clock = clock
        self._lock = threading.Lock()
        self._queue = {}
        self._outcomes = {}
        self._rules = {}
        self._required = {}
        self._updated_from = {}

    def request_update(self, pr, head_sha, base_key):
        with self._lock:
            self._queue.setdefault((pr, head_sha), base_key)

    def pool_updated_from(self, pr, head_sha):
        with self._lock:
            return head_sha in self._updated_from.get(pr, ())

    def take_outcome(self, pr):
        with self._lock:
            return self._outcomes.pop(pr, None)

    def perform(self, github):
        with self._lock:
            batch = list(self._queue.items())
            self._queue.clear()
        for (pr, head_sha), base_key in batch:
            outcome = self._perform_one(github, pr, head_sha, base_key)
            with self._lock:
                self._outcomes[pr] = outcome

    def retain(self, prs):
        with self._lock:
            self._queue = {k: v for k, v in self._queue.items() if k[0] in prs}
            self._outcomes = {k: v for k, v in self._outcomes.items() if k in prs}
            self._updated_from = {k: v for k, v in self._updated_from.items() if k in prs}

    def _perform_one(self, github, pr, head_sha, base_key):
        required = self._rule(github, base_key)
        if isinstance(required, ReadFailure):
            return WriteOutcome(RULE_FAILED, required)
        if not required:
            return WriteOutcome(NOT_REQUIRED)
        failure = github.update_branch(pr, head_sha)
        if isinstance(failure, ReadFailure):
            return WriteOutcome(UPDATE_FAILED, failure)
        with self._lock:
            self._updated_from.setdefault(pr, set()).add(head_sha)
        return WriteOutcome(UPDATED)

    def _rule(self, github, base_key):
        with self._lock:
            cached = self._rules.get(base_key)
        if cached is not None and self._clock() < cached[1]:
            return cached[0]
        value = github.requires_up_to_date(base_key)
        with self._lock:
            self._rules[base_key] = (value, self._clock() + RULE_TTL_SECONDS)
        return value

    def required_checks(self, github, base_key):
        with self._lock:
            cached = self._required.get(base_key)
        if cached is not None and self._clock() < cached[1]:
            return cached[0]
        value = github.required_checks(base_key)
        if isinstance(value, ReadFailure):
            return value
        with self._lock:
            self._required[base_key] = (value, self._clock() + RULE_TTL_SECONDS)
        return value


class InlinePrWrites(PrWrites):
    def __init__(self, github, clock):
        super().__init__(clock)
        self._github = github

    def request_update(self, pr, head_sha, base_key):
        super().request_update(pr, head_sha, base_key)
        self.perform(self._github)

