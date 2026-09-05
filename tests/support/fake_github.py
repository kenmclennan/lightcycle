from lightcycle.ports.github import GitHubEventsPort, ReadFailure


class FakeGitHub(GitHubEventsPort):
    def __init__(self, merged_prs=(), closed_prs=(), conflicted_prs=(), push_time=0.0,
                 timed_comments=None, timed_reviews=None, head_shas=None, files_by_sha=None,
                 ci_pending_by_sha=None, failing_calls=()):
        self._merged = set(merged_prs)
        self._closed = set(closed_prs)
        self._conflicted = set(conflicted_prs)
        self._push_time = push_time
        self._timed_comments = timed_comments or []
        self._timed_reviews = timed_reviews or []
        self._head_shas = head_shas or {}
        self._files_by_sha = files_by_sha or {}
        self._ci_pending_by_sha = ci_pending_by_sha or {}
        self._failing_calls = set(failing_calls)

    def is_merged(self, pr):
        return pr in self._merged

    def is_closed_unmerged(self, pr):
        return pr in self._closed

    def is_conflicted(self, pr):
        return pr in self._conflicted

    def last_push_time(self, pr):
        if "last_push_time" in self._failing_calls:
            return ReadFailure(1, "boom")
        return self._push_time

    def comments_since(self, pr, since):
        if "comments_since" in self._failing_calls:
            return ReadFailure(1, "boom")
        return [c for ts, c in self._timed_comments if ts > since and c.is_top_level]

    def pull_comments(self, pr, since):
        if "pull_comments" in self._failing_calls:
            return ReadFailure(1, "boom")
        return [c for ts, c in self._timed_comments if ts > since and not c.is_top_level]

    def reviews(self, pr, since):
        if "reviews" in self._failing_calls:
            return ReadFailure(1, "boom")
        return [r for ts, r in self._timed_reviews if ts > since]

    def head_sha(self, pr):
        return self._head_shas.get(pr, "")

    def changed_files(self, pr, sha):
        if "changed_files" in self._failing_calls:
            return ReadFailure(1, "boom")
        return self._files_by_sha.get((pr, sha), frozenset())

    def ci_pending(self, pr, sha):
        if "ci_pending" in self._failing_calls:
            return ReadFailure(1, "boom")
        return self._ci_pending_by_sha.get((pr, sha), True)
