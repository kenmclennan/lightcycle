from lightcycle.domain.pool import pr_repo
from lightcycle.ports.github import GitHubEventsPort, ListedPr, PrSync, PrView, ReadFailure


class FakeGitHub(GitHubEventsPort):
    def __init__(self, merged_prs=(), closed_prs=(), conflicted_prs=(), push_time=0.0,
                 timed_comments=None, timed_reviews=None, head_shas=None, files_by_sha=None,
                 check_runs_by_sha=None, failing_calls=(), issue_states=None,
                 behind_prs=(), strict_bases=(), base_keys=None, login="operator",
                 updated_ats=None, failing_prs=()):
        self._login = login
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
        self._failing_prs = set(failing_prs)
        self._issue_states = issue_states or {}
        self.issue_state_calls = []
        self._behind = set(behind_prs)
        self._strict_bases = set(strict_bases)
        self._base_keys = base_keys or {}
        self.update_calls = []
        self.requires_calls = []
        self.sync_calls = []
        self._updated_ats = dict(updated_ats or {})
        self._tips = {}
        self._inline_events = []
        self.calls = []
        self.rate_limit_reading = ReadFailure(-1, "no rate limit scripted")

    def rate_limit(self):
        self._record("rate_limit")
        return self.rate_limit_reading

    def _record(self, name, *args):
        self.calls.append((name,) + args)

    def touch(self, pr, ts):
        self._updated_ats[pr] = ts

    def inline_comment_on(self, pr, ts):
        self._inline_events.append((pr, ts))

    def advance_base(self, repo, base):
        key = (repo, base)
        self._tips[key] = self._tips.get(key, 0) + 1

    def known_prs(self):
        known = set(self._updated_ats) | self._merged | self._closed | set(self._head_shas)
        return sorted(known)

    def list_prs(self, repo, cutoff):
        self._record("list_prs", repo, cutoff)
        if "list_prs" in self._failing_calls:
            return ReadFailure(1, "boom")
        rows = []
        for pr in self.known_prs():
            if pr_repo(pr) != repo:
                continue
            updated = self._updated_ats.get(pr, 0.0)
            if updated < cutoff:
                continue
            closed = pr in self._merged or pr in self._closed
            rows.append(ListedPr(
                url=pr, updated_at=updated, state="closed" if closed else "open",
                merged=pr in self._merged))
        rows.sort(key=lambda r: -r.updated_at)
        return tuple(rows)

    def repo_inline_comments(self, repo, since):
        self._record("repo_inline_comments", repo, since)
        if "repo_inline_comments" in self._failing_calls:
            return ReadFailure(1, "boom")
        return frozenset(pr for pr, ts in self._inline_events if ts > since and pr_repo(pr) == repo)

    def branch_tip(self, repo, base):
        self._record("branch_tip", repo, base)
        if "branch_tip" in self._failing_calls:
            return ReadFailure(1, "boom")
        return "tip-%d" % self._tips.get((repo, base), 0)

    def pr_view(self, pr):
        self._record("pr_view", pr)
        if "pr_view" in self._failing_calls or pr in self._failing_prs:
            return ReadFailure(1, "boom")
        base_key = self._base_keys.get(pr, "acme/widget@main")
        state = "MERGED" if pr in self._merged else "CLOSED" if pr in self._closed else "OPEN"
        return PrView(
            state=state, head_sha=self._head_shas.get(pr, ""),
            base_ref=base_key.partition("@")[2], base_key=base_key,
            mergeable="CONFLICTING" if pr in self._conflicted else "MERGEABLE",
            merge_state_status="BEHIND" if pr in self._behind else "CLEAN",
            updated_at=self._updated_ats.get(pr, 0.0))

    def authenticated_login(self):
        if "authenticated_login" in self._failing_calls:
            return ReadFailure(1, "boom")
        return self._login

    def issue_state(self, url):
        self.issue_state_calls.append(url)
        if "issue_state" in self._failing_calls:
            return ReadFailure(1, "boom")
        if url not in self._issue_states:
            return ReadFailure(1, "not found")
        return self._issue_states[url]

    def is_merged(self, pr):
        self._record("is_merged", pr)
        if "is_merged" in self._failing_calls:
            return ReadFailure(1, "boom")
        return pr in self._merged

    def is_closed_unmerged(self, pr):
        self._record("is_closed_unmerged", pr)
        if "is_closed_unmerged" in self._failing_calls:
            return ReadFailure(1, "boom")
        return pr in self._closed

    def last_push_time(self, pr):
        self._record("last_push_time", pr)
        if "last_push_time" in self._failing_calls:
            return ReadFailure(1, "boom")
        return self._push_time

    def comments_since(self, pr, since):
        self._record("comments_since", pr, since)
        if "comments_since" in self._failing_calls:
            return ReadFailure(1, "boom")
        return [c for ts, c in self._timed_comments if ts > since and c.is_top_level]

    def pull_comments(self, pr, since):
        self._record("pull_comments", pr, since)
        if "pull_comments" in self._failing_calls:
            return ReadFailure(1, "boom")
        return [c for ts, c in self._timed_comments if ts > since and not c.is_top_level]

    def reviews(self, pr, since):
        self._record("reviews", pr, since)
        if "reviews" in self._failing_calls:
            return ReadFailure(1, "boom")
        return [r for ts, r in self._timed_reviews if ts > since]

    def head_sha(self, pr):
        self._record("head_sha", pr)
        if "head_sha" in self._failing_calls:
            return ReadFailure(1, "boom")
        return self._head_shas.get(pr, "")

    def changed_files(self, pr, sha, base=None):
        self._record("changed_files", pr, sha)
        if "changed_files" in self._failing_calls:
            return ReadFailure(1, "boom")
        return self._files_by_sha.get((pr, sha), frozenset())

    def check_runs(self, pr, sha):
        self._record("check_runs", pr, sha)
        if "check_runs" in self._failing_calls:
            return ReadFailure(1, "boom")
        return self._check_runs_by_sha.get((pr, sha), ())

    def pr_sync_state(self, pr):
        self.sync_calls.append(pr)
        self._record("pr_sync_state", pr)
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
