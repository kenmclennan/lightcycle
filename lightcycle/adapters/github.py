import datetime
import json
import re
import subprocess

from lightcycle.ports.github import Comment, GitHubEventsPort, Review

_PR_URL_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)")


def _parse_iso(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _repo_parts(pr):
    m = _PR_URL_RE.match(pr)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


class GitHubEventsAdapter(GitHubEventsPort):
    def _pr_state(self, pr: str) -> str:
        result = subprocess.run(
            ["gh", "pr", "view", pr, "--json", "state"], capture_output=True, text=True
        )
        if result.returncode != 0:
            return ""
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return ""
        return data.get("state", "")

    def is_merged(self, pr: str) -> bool:
        return self._pr_state(pr) == "MERGED"

    def is_closed_unmerged(self, pr: str) -> bool:
        return self._pr_state(pr) == "CLOSED"

    def is_conflicted(self, pr: str) -> bool:
        result = subprocess.run(
            ["gh", "pr", "view", pr, "--json", "mergeable,mergeStateStatus"],
            capture_output=True, text=True)
        if result.returncode != 0:
            return False
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return False
        return (data.get("mergeable") == "CONFLICTING"
                or data.get("mergeStateStatus") == "DIRTY")

    def last_push_time(self, pr: str) -> float:
        parts = _repo_parts(pr)
        if not parts:
            return 0.0
        owner, repo, number = parts
        result = subprocess.run(
            ["gh", "api", "/repos/%s/%s/pulls/%s/commits" % (owner, repo, number)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return 0.0
        try:
            commits = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return 0.0
        if not commits:
            return 0.0
        last = commits[-1]
        date_str = last.get("commit", {}).get("committer", {}).get("date", "")
        if not date_str:
            return 0.0
        try:
            return _parse_iso(date_str)
        except (ValueError, KeyError):
            return 0.0

    def comments_since(self, pr: str, since: float):
        parts = _repo_parts(pr)
        if not parts:
            return []
        owner, repo, number = parts
        result = []

        r = subprocess.run(
            ["gh", "api", "--paginate", "/repos/%s/%s/issues/%s/comments" % (owner, repo, number)],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            try:
                for c in json.loads(r.stdout):
                    created = _parse_iso(c.get("created_at", "1970-01-01T00:00:00Z"))
                    if created > since:
                        result.append(
                            Comment(
                                author=c.get("user", {}).get("login", ""),
                                body=c.get("body", ""),
                                is_top_level=True,
                                id=str(c["id"]) if c.get("id") is not None else None,
                                created_at=created,
                            )
                        )
            except (json.JSONDecodeError, ValueError):
                pass

        return result

    def pull_comments(self, pr: str, since: float):
        parts = _repo_parts(pr)
        if not parts:
            return []
        owner, repo, number = parts
        result = []

        r = subprocess.run(
            ["gh", "api", "--paginate", "/repos/%s/%s/pulls/%s/comments" % (owner, repo, number)],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            try:
                for c in json.loads(r.stdout):
                    created = _parse_iso(c.get("created_at", "1970-01-01T00:00:00Z"))
                    if created > since:
                        result.append(
                            Comment(
                                author=c.get("user", {}).get("login", ""),
                                body=c.get("body", ""),
                                is_top_level=False,
                                path=c.get("path"),
                                line=c.get("line"),
                                id=str(c["id"]) if c.get("id") is not None else None,
                                in_reply_to_id=(
                                    str(c["in_reply_to_id"])
                                    if c.get("in_reply_to_id") is not None else None
                                ),
                                created_at=created,
                            )
                        )
            except (json.JSONDecodeError, ValueError):
                pass

        return result

    def reviews(self, pr: str, since: float):
        parts = _repo_parts(pr)
        if not parts:
            return []
        owner, repo, number = parts
        result = []

        r = subprocess.run(
            ["gh", "api", "--paginate", "/repos/%s/%s/pulls/%s/reviews" % (owner, repo, number)],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            try:
                for rv in json.loads(r.stdout):
                    submitted = _parse_iso(rv.get("submitted_at") or "1970-01-01T00:00:00Z")
                    if submitted > since:
                        result.append(
                            Review(
                                author=rv.get("user", {}).get("login", ""),
                                body=rv.get("body", ""),
                                created_at=submitted,
                            )
                        )
            except (json.JSONDecodeError, ValueError):
                pass

        return result
