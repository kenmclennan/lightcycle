from lightcycle.ports.github import GitHubEventsPort, PrSync, ReadFailure


class FakeGitHub(GitHubEventsPort):
    def __init__(self, merged_prs=(), closed_prs=(), conflicted_prs=(), push_time=0.0,
                 timed_comments=None, timed_reviews=None, head_shas=None, files_by_sha=None,
                 check_runs_by_sha=None, failing_calls=(), issue_states=None,
                 behind_prs=(), strict_bases=(), base_keys=None):
        self._merged = set(merged_prs)
        self._closed = set(closed_prs)
        self._conflicted = set(conflicted_prs)
        self._push_time = push_time
        self._timed_comments = timed_comments or []
        self._timed_reviews = timed_reviews or []
        self._head_shas = head_shas or {}
        self._files_by_sha = files_by_sha or {}
        self._check_runs_by_sha = check_runs_by_sha or {}
        self._failing_calls = set(failing_calls)
        self._issue_states = issue_states or {}
        self.issue_state_calls = []
        self._behind = set(behind_prs)
        self._strict_bases = set(strict_bases)
        self._base_keys = base_keys or {}
        self.update_calls = []
        self.requires_calls = []
        self.sync_calls = []

    def issue_state(self, url):
        self.issue_state_calls.append(url)
        if "issue_state" in self._failing_calls:
            return ReadFailure(1, "boom")
        if url not in self._issue_states:
            return ReadFailure(1, "not found")
        return self._issue_states[url]

    def is_merged(self, pr):
        if "is_merged" in self._failing_calls:
            return ReadFailure(1, "boom")
        return pr in self._merged

    def is_closed_unmerged(self, pr):
        if "is_closed_unmerged" in self._failing_calls:
            return ReadFailure(1, "boom")
        return pr in self._closed

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
        if "head_sha" in self._failing_calls:
            return ReadFailure(1, "boom")
        return self._head_shas.get(pr, "")

    def changed_files(self, pr, sha):
        if "changed_files" in self._failing_calls:
            return ReadFailure(1, "boom")
        return self._files_by_sha.get((pr, sha), frozenset())

    def check_runs(self, pr, sha):
        if "check_runs" in self._failing_calls:
            return ReadFailure(1, "boom")
        return self._check_runs_by_sha.get((pr, sha), ())

    def pr_sync_state(self, pr):
        self.sync_calls.append(pr)
        if "pr_sync_state" in self._failing_calls:
            return ReadFailure(1, "boom")
        return PrSync(
            behind=pr in self._behind,
            conflicted=pr in self._conflicted,
            head_sha=self._head_shas.get(pr, ""),
            base_key=self._base_keys.get(pr, "acme/widget@main"),
        )

    def requires_up_to_date(self, base_key):
        self.requires_calls.append(base_key)
        if "requires_up_to_date" in self._failing_calls:
            return ReadFailure(1, "boom")
        return base_key in self._strict_bases

    def update_branch(self, pr, expected_head_sha):
        self.update_calls.append((pr, expected_head_sha))
        if "update_branch" in self._failing_calls:
            return ReadFailure(1, "boom")
        if expected_head_sha != self._head_shas.get(pr, ""):
            return ReadFailure(1, "HTTP 422: expected head sha did not match")
        self._behind.discard(pr)
        self._head_shas[pr] = expected_head_sha + "-updated"
        return None
