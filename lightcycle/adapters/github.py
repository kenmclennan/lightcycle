import datetime
import json
import re
import subprocess
from typing import Optional, Tuple, Union

from lightcycle.ports.github import (
    CheckRun, Comment, GitHubEventsPort, ListedPr, PrSync, PrView, RateLimit, ReadFailure, Review,
)

_PR_URL_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)")
_GH_TIMEOUT_SECONDS = 30
_LISTING_PAGE_SIZE = 100
_PULL_API_URL_RE = re.compile(r"/repos/([^/]+)/([^/]+)/pulls/(\d+)$")


def _timeout_read_failure():
    return ReadFailure(-1, "gh timed out after %ds" % _GH_TIMEOUT_SECONDS)


def _parse_iso(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo_parts(pr):
    m = _PR_URL_RE.match(pr)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


class GitHubEventsAdapter(GitHubEventsPort):
    def _pr_state(self, pr: str) -> Union[str, ReadFailure]:
        try:
            result = subprocess.run(
                ["gh", "pr", "view", pr, "--json", "state"], capture_output=True, text=True,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return ReadFailure(-1, "could not parse gh pr view JSON for state")
        return data.get("state", "")

    def issue_state(self, url: str) -> Union[str, ReadFailure]:
        try:
            result = subprocess.run(
                ["gh", "issue", "view", url, "--json", "state"], capture_output=True, text=True,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return ReadFailure(-1, "could not parse gh issue view JSON for state")
        return data.get("state", "")

    def is_merged(self, pr: str) -> Union[bool, ReadFailure]:
        state = self._pr_state(pr)
        return state if isinstance(state, ReadFailure) else state == "MERGED"

    def is_closed_unmerged(self, pr: str) -> Union[bool, ReadFailure]:
        state = self._pr_state(pr)
        return state if isinstance(state, ReadFailure) else state == "CLOSED"

    def last_push_time(self, pr: str) -> Union[float, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, _number = parts
        sha = self.head_sha(pr)
        if isinstance(sha, ReadFailure):
            return sha
        if not sha:
            return ReadFailure(-1, "gh returned no head sha for %r" % pr)
        try:
            result = subprocess.run(
                [
                    "gh", "api", "/repos/%s/%s/commits/%s" % (owner, repo, sha),
                    "--jq", ".commit.committer.date // empty",
                ],
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        date_str = result.stdout.strip()
        if not date_str:
            return ReadFailure(-1, "gh returned no commit date for %r" % pr)
        try:
            return _parse_iso(date_str)
        except (ValueError, KeyError):
            return ReadFailure(-1, "could not parse commit date %r for %r" % (date_str, pr))

    def comments_since(self, pr: str, since: float):
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, number = parts
        result = []

        jq = (
            ".[] | select((.created_at|fromdateiso8601) > %s) | "
            "{author: .user.login, body, id, created_at: (.created_at|fromdateiso8601)}"
            % since
        )
        try:
            r = subprocess.run(
                [
                    "gh", "api", "--paginate",
                    "/repos/%s/%s/issues/%s/comments?per_page=100" % (owner, repo, number),
                    "--jq", jq,
                ],
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
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
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, number = parts
        result = []

        jq = (
            ".[] | select((.created_at|fromdateiso8601) > %s) | "
            "{author: .user.login, body, id, in_reply_to_id, path, line, "
            "pull_request_review_id, created_at: (.created_at|fromdateiso8601)}"
            % since
        )
        try:
            r = subprocess.run(
                [
                    "gh", "api", "--paginate",
                    "/repos/%s/%s/pulls/%s/comments?per_page=100" % (owner, repo, number),
                    "--jq", jq,
                ],
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
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
                    review_id=(
                        str(c["pull_request_review_id"])
                        if c.get("pull_request_review_id") is not None else None
                    ),
                )
            )

        return result

    def head_sha(self, pr: str) -> Union[str, ReadFailure]:
        try:
            result = subprocess.run(
                ["gh", "pr", "view", pr, "--json", "headRefOid"], capture_output=True, text=True,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return ReadFailure(-1, "could not parse gh pr view JSON for headRefOid")
        return data.get("headRefOid", "")

    def changed_files(
        self, pr: str, sha: str, base: Optional[str] = None
    ) -> Union[frozenset, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, number = parts
        if base is None:
            try:
                result = subprocess.run(
                    ["gh", "pr", "view", pr, "--json", "baseRefName"],
                    capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                return _timeout_read_failure()
            if result.returncode != 0:
                return ReadFailure(result.returncode, result.stderr)
            try:
                base = json.loads(result.stdout).get("baseRefName", "")
            except (json.JSONDecodeError, ValueError):
                return ReadFailure(-1, "could not parse gh pr view JSON for baseRefName")
        if not base:
            return ReadFailure(-1, "gh pr view returned an empty baseRefName for %r" % pr)
        try:
            r = subprocess.run(
                [
                    "gh", "api", "/repos/%s/%s/compare/%s...%s" % (owner, repo, base, sha),
                    "--jq", "[.files[]?.filename]",
                ],
                capture_output=True, text=True,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if r.returncode != 0:
            return ReadFailure(r.returncode, r.stderr)
        try:
            filenames = json.loads(r.stdout)
        except (json.JSONDecodeError, ValueError):
            return ReadFailure(-1, "could not parse gh api compare JSON for changed filenames")
        return frozenset(f for f in filenames if f)

    def check_runs(self, pr: str, sha: str) -> Union[Tuple[CheckRun, ...], ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, _number = parts
        rows = self._gh_api_lines(
            "/repos/%s/%s/commits/%s/check-runs?per_page=100" % (owner, repo, sha),
            ".total_count as $total | .check_runs[] | "
            "{name,status,conclusion,started_at,url:.html_url,total:$total}",
            paginate=True,
        )
        if isinstance(rows, ReadFailure):
            return rows
        data = rows
        if data and any(c.get("total") != len(data) for c in data):
            return ReadFailure(
                -1,
                "check-runs total_count %s does not match the %d runs returned"
                % (data[0].get("total"), len(data)),
            )
        return tuple(
            CheckRun(
                name=c.get("name") or "",
                status=c.get("status") or "",
                conclusion=c.get("conclusion"),
                url=c.get("url") or "",
                started_at=_parse_iso(c["started_at"]) if c.get("started_at") else 0.0,
            )
            for c in data
        )

    def reviews(self, pr: str, since: float):
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, number = parts
        result = []

        jq = (
            '.[] | select(((.submitted_at // "1970-01-01T00:00:00Z")|fromdateiso8601) > %s) | '
            '{id, author: .user.login, body, state, '
            'created_at: ((.submitted_at // "1970-01-01T00:00:00Z")|fromdateiso8601)}'
            % since
        )
        try:
            r = subprocess.run(
                [
                    "gh", "api", "--paginate",
                    "/repos/%s/%s/pulls/%s/reviews?per_page=100" % (owner, repo, number),
                    "--jq", jq,
                ],
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
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
                    id=str(rv["id"]) if rv.get("id") is not None else None,
                )
            )

        return result

    def authenticated_login(self) -> Union[str, ReadFailure]:
        try:
            r = subprocess.run(
                ["gh", "api", "user", "--jq", ".login"],
                capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if r.returncode != 0:
            return ReadFailure(r.returncode, r.stderr)
        return r.stdout.strip()

    def pr_sync_state(self, pr: str) -> Union[PrSync, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, _ = parts
        try:
            result = subprocess.run(
                ["gh", "pr", "view", pr, "--json", "mergeable,mergeStateStatus,headRefOid,baseRefName"],
                capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return ReadFailure(-1, "could not parse gh pr view JSON for sync state")
        return PrSync(
            behind=data.get("mergeStateStatus") == "BEHIND",
            conflicted=(data.get("mergeable") == "CONFLICTING"
                        or data.get("mergeStateStatus") == "DIRTY"),
            head_sha=data.get("headRefOid") or "",
            base_key="%s/%s@%s" % (owner, repo, data.get("baseRefName") or ""),
        )

    def _gh_api_json(self, path):
        try:
            result = subprocess.run(
                ["gh", "api", path], capture_output=True, text=True,
                timeout=_GH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        try:
            return json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return ReadFailure(-1, "could not parse gh api JSON for %s" % path)

    def rate_limit(self) -> Union[RateLimit, ReadFailure]:
        data = self._gh_api_json("rate_limit")
        if isinstance(data, ReadFailure):
            return data
        core = ((data or {}).get("resources") or {}).get("core") if isinstance(data, dict) else None
        if not isinstance(core, dict):
            return ReadFailure(-1, "rate_limit response carries no core bucket")
        fields = [core.get(k) for k in ("limit", "remaining", "reset")]
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in fields):
            return ReadFailure(-1, "rate_limit core bucket has a missing or non-integer field")
        return RateLimit(limit=fields[0], remaining=fields[1], reset=fields[2])

    def requires_up_to_date(self, base_key: str) -> Union[bool, ReadFailure]:
        repo_path, _, base = base_key.partition("@")
        rules = self._gh_api_json("repos/%s/rules/branches/%s" % (repo_path, base))
        if isinstance(rules, ReadFailure):
            return rules
        if isinstance(rules, list) and any(
            isinstance(r, dict) and r.get("type") == "required_status_checks"
            and (r.get("parameters") or {}).get("strict_required_status_checks_policy") is True
            for r in rules
        ):
            return True
        try:
            result = subprocess.run(
                ["gh", "api",
                 "repos/%s/branches/%s/protection/required_status_checks" % (repo_path, base)],
                capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            if "404" in result.stderr or "Not Found" in result.stderr \
                    or "not protected" in result.stderr.lower():
                return False
            return ReadFailure(result.returncode, result.stderr)
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return ReadFailure(-1, "could not parse gh api JSON for required status checks")
        return isinstance(data, dict) and data.get("strict") is True

    def required_checks(self, base_key: str) -> Union[Optional[frozenset], ReadFailure]:
        repo_path, _, base = base_key.partition("@")
        rules = self._gh_api_json("repos/%s/rules/branches/%s" % (repo_path, base))
        if isinstance(rules, ReadFailure):
            return rules
        names = set()
        for rule in rules if isinstance(rules, list) else []:
            if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
                continue
            for entry in (rule.get("parameters") or {}).get("required_status_checks") or []:
                if isinstance(entry, dict) and entry.get("context"):
                    names.add(entry["context"])
        try:
            result = subprocess.run(
                ["gh", "api",
                 "repos/%s/branches/%s/protection/required_status_checks" % (repo_path, base)],
                capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            if "404" in result.stderr or "Not Found" in result.stderr \
                    or "not protected" in result.stderr.lower():
                return frozenset(names) or None
            return ReadFailure(result.returncode, result.stderr)
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return ReadFailure(-1, "could not parse gh api JSON for required status checks")
        if isinstance(data, dict):
            names.update(c for c in data.get("contexts") or [] if c)
            for entry in data.get("checks") or []:
                if isinstance(entry, dict) and entry.get("context"):
                    names.add(entry["context"])
        return frozenset(names) or None

    def update_branch(self, pr: str, expected_head_sha: str) -> Union[None, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, number = parts
        try:
            result = subprocess.run(
                ["gh", "api", "-X", "PUT",
                 "repos/%s/%s/pulls/%s/update-branch" % (owner, repo, number),
                 "-f", "expected_head_sha=%s" % expected_head_sha,
                 "-f", "update_method=rebase"],
                capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        return None

    def _gh_api_lines(self, path, jq, paginate=False):
        argv = ["gh", "api"] + (["--paginate"] if paginate else []) + [path, "--jq", jq]
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        rows = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                return ReadFailure(-1, "could not parse gh api JSON line for %s" % path)
        return rows

    def list_prs(self, repo: str, cutoff: float) -> Union[Tuple[ListedPr, ...], ReadFailure]:
        listed = []
        page = 1
        while True:
            rows = self._gh_api_lines(
                "repos/%s/pulls?state=all&sort=updated&direction=desc&per_page=%d&page=%d"
                % (repo, _LISTING_PAGE_SIZE, page),
                ".[] | {url: .html_url, updated_at, state, merged_at}",
            )
            if isinstance(rows, ReadFailure):
                return rows
            last = None
            for row in rows:
                try:
                    updated = _parse_iso(row["updated_at"])
                except (KeyError, ValueError, TypeError, AttributeError):
                    return ReadFailure(-1, "could not parse updated_at in the pulls listing")
                last = updated
                if updated >= cutoff:
                    listed.append(ListedPr(
                        url=row.get("url") or "", updated_at=updated,
                        state=row.get("state") or "", merged=bool(row.get("merged_at")),
                    ))
            if last is None or last < cutoff or len(rows) < _LISTING_PAGE_SIZE:
                return tuple(listed)
            page += 1

    def repo_inline_comments(self, repo: str, since: float) -> Union[frozenset, ReadFailure]:
        rows = self._gh_api_lines(
            "repos/%s/pulls/comments?since=%s&sort=updated&direction=desc&per_page=%d"
            % (repo, _iso(since), _LISTING_PAGE_SIZE),
            ".[] | .pull_request_url",
            paginate=True,
        )
        if isinstance(rows, ReadFailure):
            return rows
        urls = set()
        for api_url in rows:
            m = _PULL_API_URL_RE.search(api_url or "")
            if m:
                urls.add("https://github.com/%s/%s/pull/%s" % m.groups())
        return frozenset(urls)

    def branch_tip(self, repo: str, base: str) -> Union[str, ReadFailure]:
        try:
            result = subprocess.run(
                ["gh", "api", "repos/%s/branches/%s" % (repo, base), "--jq", ".commit.sha"],
                capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        tip = result.stdout.strip()
        if not tip:
            return ReadFailure(-1, "gh returned no tip sha for %s@%s" % (repo, base))
        return tip

    def pr_view(self, pr: str) -> Union[PrView, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, _ = parts
        try:
            result = subprocess.run(
                [
                    "gh", "pr", "view", pr, "--json",
                    "state,headRefOid,baseRefName,mergeable,mergeStateStatus,updatedAt",
                ],
                capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if result.returncode != 0:
            return ReadFailure(result.returncode, result.stderr)
        try:
            data = json.loads(result.stdout)
            updated = _parse_iso(data["updatedAt"])
        except (json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError):
            return ReadFailure(-1, "could not parse gh pr view JSON for the shared view")
        base = data.get("baseRefName") or ""
        return PrView(
            state=data.get("state") or "",
            head_sha=data.get("headRefOid") or "",
            base_ref=base,
            base_key="%s/%s@%s" % (owner, repo, base),
            mergeable=data.get("mergeable") or "",
            merge_state_status=data.get("mergeStateStatus") or "",
            updated_at=updated,
        )
