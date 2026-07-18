from lightcycle.ports.github import GitHubEventsPort


class FakeGitHub(GitHubEventsPort):
    def __init__(self, merged_prs=(), closed_prs=(), conflicted_prs=(), push_time=0.0,
                 timed_comments=None, timed_reviews=None):
        self._merged = set(merged_prs)
        self._closed = set(closed_prs)
        self._conflicted = set(conflicted_prs)
        self._push_time = push_time
        self._timed_comments = timed_comments or []
        self._timed_reviews = timed_reviews or []

    def is_merged(self, pr):
        return pr in self._merged

    def is_closed_unmerged(self, pr):
        return pr in self._closed

    def is_conflicted(self, pr):
        return pr in self._conflicted

    def last_push_time(self, pr):
        return self._push_time

    def comments_since(self, pr, since):
        return [c for ts, c in self._timed_comments if ts > since and c.is_top_level]

    def pull_comments(self, pr, since):
        return [c for ts, c in self._timed_comments if ts > since and not c.is_top_level]

    def reviews(self, pr, since):
        return [r for ts, r in self._timed_reviews if ts > since]
