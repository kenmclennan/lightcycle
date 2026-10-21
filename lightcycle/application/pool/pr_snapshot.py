import threading
from dataclasses import dataclass, field, replace
from typing import Optional

from lightcycle.ports.github import GitHubEventsPort, NotYetRead, PrSync, PrView, ReadFailure


@dataclass(frozen=True)
class PrEntry:
    state: str = ""
    view: Optional[PrView] = None
    updated_at: float = 0.0
    push_time: object = None
    comments: object = None
    pull_comments: object = None
    reviews: object = None
    stale: bool = False


@dataclass(frozen=True)
class Wanted:
    prs: frozenset = frozenset()
    files: frozenset = frozenset()
    checks: frozenset = frozenset()


@dataclass
class _Pending:
    prs: set = field(default_factory=set)
    files: set = field(default_factory=set)
    checks: set = field(default_factory=set)


class PrSnapshot(GitHubEventsPort):
    def __init__(self, github):
        self._github = github
        self._lock = threading.Lock()
        self._entries = {}
        self._files = {}
        self._checks = {}
        self._required = {}
        self._pending = _Pending()

    def _entry(self, pr):
        with self._lock:
            self._pending.prs.add(pr)
            return self._entries.get(pr)

    def entry_of(self, pr):
        with self._lock:
            return self._entries.get(pr)

    def is_stale(self, pr):
        entry = self.entry_of(pr)
        return entry is not None and entry.stale

    def take_wanted(self):
        with self._lock:
            pending, self._pending = self._pending, _Pending()
        return Wanted(
            prs=frozenset(pending.prs), files=frozenset(pending.files),
            checks=frozenset(pending.checks),
        )

    def publish(self, pr, entry):
        with self._lock:
            self._entries[pr] = entry

    def publish_files(self, pr, sha, files):
        with self._lock:
            self._files[(pr, sha)] = files

    def publish_checks(self, pr, sha, runs):
        with self._lock:
            self._checks[(pr, sha)] = runs

    def publish_required(self, base_key, value):
        with self._lock:
            self._required[base_key] = value

    def mark_stale(self, pr):
        with self._lock:
            current = self._entries.get(pr)
            if current is None:
                self._entries[pr] = PrEntry(stale=True)
            else:
                self._entries[pr] = replace(current, stale=True)

    def known_files(self, pr, sha):
        with self._lock:
            return (pr, sha) in self._files

    def retain(self, prs, check_prs):
        with self._lock:
            self._entries = {pr: e for pr, e in self._entries.items() if pr in prs}
            self._files = {k: v for k, v in self._files.items() if k[0] in prs}
            self._checks = {
                k: v for k, v in self._checks.items() if k[0] in prs and k[0] in check_prs
            }

    def authenticated_login(self):
        return self._github.authenticated_login()

    def issue_state(self, url):
        return self._github.issue_state(url)

    def requires_up_to_date(self, base_key):
        return self._github.requires_up_to_date(base_key)

    def required_checks(self, base_key):
        with self._lock:
            if base_key in self._required:
                return self._required[base_key]
        return NotYetRead()

    def update_branch(self, pr, expected_head_sha):
        return self._github.update_branch(pr, expected_head_sha)

    def list_prs(self, repo, cutoff):
        return self._github.list_prs(repo, cutoff)

    def repo_inline_comments(self, repo, since):
        return self._github.repo_inline_comments(repo, since)

    def branch_tip(self, repo, base):
        return self._github.branch_tip(repo, base)

    def pr_view(self, pr):
        return self._github.pr_view(pr)

    def _state(self, pr):
        entry = self._entry(pr)
        if entry is None or not entry.state:
            return NotYetRead()
        return entry.state

    def is_merged(self, pr):
        state = self._state(pr)
        return state if isinstance(state, ReadFailure) else state == "MERGED"

    def is_closed_unmerged(self, pr):
        state = self._state(pr)
        return state if isinstance(state, ReadFailure) else state == "CLOSED"

    def _view(self, pr):
        entry = self._entry(pr)
        if entry is None or entry.view is None:
            return NotYetRead()
        return entry.view

    def head_sha(self, pr):
        view = self._view(pr)
        return view if isinstance(view, ReadFailure) else view.head_sha

    def rate_limit(self):
        return self._github.rate_limit()

    def pr_sync_state(self, pr):
        view = self._view(pr)
        if isinstance(view, ReadFailure):
            return view
        return PrSync(
            behind=view.merge_state_status == "BEHIND",
            conflicted=view.mergeable == "CONFLICTING" or view.merge_state_status == "DIRTY",
            head_sha=view.head_sha,
            base_key=view.base_key,
        )

    def last_push_time(self, pr):
        entry = self._entry(pr)
        if entry is None or entry.push_time is None:
            return NotYetRead()
        return entry.push_time

    def _timed(self, pr, attr, since):
        entry = self._entry(pr)
        items = getattr(entry, attr) if entry is not None else None
        if items is None:
            return NotYetRead()
        if isinstance(items, ReadFailure):
            return items
        return [i for i in items if i.created_at > since]

    def comments_since(self, pr, since):
        return self._timed(pr, "comments", since)

    def pull_comments(self, pr, since):
        return self._timed(pr, "pull_comments", since)

    def reviews(self, pr, since):
        return self._timed(pr, "reviews", since)

    def changed_files(self, pr, sha, base=None):
        self._entry(pr)
        with self._lock:
            if (pr, sha) in self._files:
                return self._files[(pr, sha)]
            self._pending.files.add((pr, sha))
        return NotYetRead()

    def check_runs(self, pr, sha):
        self._entry(pr)
        with self._lock:
            self._pending.checks.add(pr)
            if (pr, sha) in self._checks:
                return self._checks[(pr, sha)]
        return NotYetRead()
