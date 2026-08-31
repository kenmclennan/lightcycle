import datetime
import json
import re
import subprocess
from typing import Union

from lightcycle.ports.github import Comment, GitHubEventsPort, ReadFailure, Review

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

    def last_push_time(self, pr: str) -> Union[float, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return 0.0
        owner, repo, number = parts
        result = subprocess.run(
            [
                "gh", "api", "/repos/%s/%s/pulls/%s/commits" % (owner, repo, number),
                "--jq", ".[-1].commit.committer.date // empty",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        date_str = result.stdout.strip()
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

        jq = (
            ".[] | select((.created_at|fromdateiso8601) > %s) | "
            "{author: .user.login, body, id, created_at: (.created_at|fromdateiso8601)}"
            % since
        )
        r = subprocess.run(
            [
                "gh", "api", "--paginate",
                "/repos/%s/%s/issues/%s/comments" % (owner, repo, number),
                "--jq", jq,
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            return ReadFailure(r.returncode, r.stderr)
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                c = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            result.append(
                Comment(
                    author=c.get("author") or "",
                    body=c.get("body") or "",
                    is_top_level=True,
                    id=str(c["id"]) if c.get("id") is not None else None,
                    created_at=c.get("created_at", 0.0),
                )
            )

        return result

    def pull_comments(self, pr: str, since: float):
        parts = _repo_parts(pr)
        if not parts:
            return []
        owner, repo, number = parts
        result = []

        jq = (
            ".[] | select((.created_at|fromdateiso8601) > %s) | "
            "{author: .user.login, body, id, in_reply_to_id, path, line, "
            "created_at: (.created_at|fromdateiso8601)}"
            % since
        )
        r = subprocess.run(
            [
                "gh", "api", "--paginate",
                "/repos/%s/%s/pulls/%s/comments" % (owner, repo, number),
                "--jq", jq,
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            return ReadFailure(r.returncode, r.stderr)
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                c = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            result.append(
                Comment(
                    author=c.get("author") or "",
                    body=c.get("body") or "",
                    is_top_level=False,
                    path=c.get("path"),
                    line=c.get("line"),
                    id=str(c["id"]) if c.get("id") is not None else None,
                    in_reply_to_id=(
                        str(c["in_reply_to_id"])
                        if c.get("in_reply_to_id") is not None else None
                    ),
                    created_at=c.get("created_at", 0.0),
                )
            )

        return result

    def head_sha(self, pr: str) -> str:
        result = subprocess.run(
            ["gh", "pr", "view", pr, "--json", "headRefOid"], capture_output=True, text=True
        )
        if result.returncode != 0:
            return ""
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return ""
        return data.get("headRefOid", "")

    def changed_files(self, pr: str, sha: str) -> Union[frozenset, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return frozenset()
        owner, repo, number = parts
        result = subprocess.run(
            ["gh", "pr", "view", pr, "--json", "baseRefName"], capture_output=True, text=True
        )
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        try:
            base = json.loads(result.stdout).get("baseRefName", "")
        except (json.JSONDecodeError, ValueError):
            return frozenset()
        if not base:
            return frozenset()
        r = subprocess.run(
            [
                "gh", "api", "/repos/%s/%s/compare/%s...%s" % (owner, repo, base, sha),
                "--jq", "[.files[]?.filename]",
            ],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return ReadFailure(r.returncode, r.stderr)
        try:
            filenames = json.loads(r.stdout)
        except (json.JSONDecodeError, ValueError):
            return frozenset()
        return frozenset(f for f in filenames if f)

    def reviews(self, pr: str, since: float):
        parts = _repo_parts(pr)
        if not parts:
            return []
        owner, repo, number = parts
        result = []

        jq = (
            '.[] | select(((.submitted_at // "1970-01-01T00:00:00Z")|fromdateiso8601) > %s) | '
            '{author: .user.login, body, state, '
            'created_at: ((.submitted_at // "1970-01-01T00:00:00Z")|fromdateiso8601)}'
            % since
        )
        r = subprocess.run(
            [
                "gh", "api", "--paginate",
                "/repos/%s/%s/pulls/%s/reviews" % (owner, repo, number),
                "--jq", jq,
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            return ReadFailure(r.returncode, r.stderr)
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rv = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            result.append(
                Review(
                    author=rv.get("author") or "",
                    body=rv.get("body") or "",
                    created_at=rv.get("created_at", 0.0),
                    state=rv.get("state") or "",
                )
            )

        return result
