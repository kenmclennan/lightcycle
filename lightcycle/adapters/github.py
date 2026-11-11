import datetime
import hashlib
import json
import os
import re
import subprocess
from typing import Optional, Tuple, Union

from lightcycle.ports.github import (
    CheckRun, Comment, GitHubEventsPort, ListedPr, PrSync, PrView, RateLimit, ReadFailure, Review,
    StackLayer, WorkflowFile,
)

_PR_URL_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)")
_STACK_URL_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/stack/(\d+)$")
_GH_TIMEOUT_SECONDS = 30
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_ACTIONS_RUN_URL = re.compile(r"/actions/runs/(\d+)/")


def _actions_run_id(url):
    m = _ACTIONS_RUN_URL.search(url)
    return m.group(1) if m else ""
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
    def __init__(self, base_env=None):
        self._base_env = dict(base_env) if base_env is not None else {}

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

    def _fresh_head_sha(self, owner: str, repo: str, number: str) -> Optional[str]:
        ref = "refs/pull/%s/head" % number
        try:
            result = subprocess.run(
                ["git", "ls-remote", "https://github.com/%s/%s.git" % (owner, repo), ref],
                capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS,
                env={**self._base_env, "GIT_TERMINAL_PROMPT": "0"},
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == ref:
                return fields[0] if _SHA_RE.fullmatch(fields[0]) else None
        return None

    def last_push_time(self, pr: str) -> Union[float, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, number = parts
        sha = self._fresh_head_sha(owner, repo, number)
        if sha is None:
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

    def _resolve_base(self, pr, base):
        if base is not None:
            return base or ReadFailure(-1, "gh pr view returned an empty baseRefName for %r" % pr)
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
            resolved = json.loads(result.stdout).get("baseRefName", "")
        except (json.JSONDecodeError, ValueError):
            return ReadFailure(-1, "could not parse gh pr view JSON for baseRefName")
        if not resolved:
            return ReadFailure(-1, "gh pr view returned an empty baseRefName for %r" % pr)
        return resolved

    def changed_files(
        self, pr: str, sha: str, base: Optional[str] = None
    ) -> Union[frozenset, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, number = parts
        base = self._resolve_base(pr, base)
        if isinstance(base, ReadFailure):
            return base
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

    def pr_files(self, pr: str) -> Union[frozenset, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, number = parts
        try:
            r = subprocess.run(
                [
                    "gh", "api", "--paginate",
                    "/repos/%s/%s/pulls/%s/files?per_page=100" % (owner, repo, number),
                    "--jq", ".[].filename",
                ],
                capture_output=True, text=True,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if r.returncode != 0:
            return ReadFailure(r.returncode, r.stderr)
        return frozenset(line for line in r.stdout.splitlines() if line)

    def diff_signature(
        self, pr: str, sha: str, base: Optional[str] = None
    ) -> Union[str, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, number = parts
        base = self._resolve_base(pr, base)
        if isinstance(base, ReadFailure):
            return base
        try:
            r = subprocess.run(
                [
                    "gh", "api", "/repos/%s/%s/compare/%s...%s" % (owner, repo, base, sha),
                    "--jq", "[.files[]? | {filename, patch, sha}]",
                ],
                capture_output=True, text=True,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if r.returncode != 0:
            return ReadFailure(r.returncode, r.stderr)
        try:
            files = json.loads(r.stdout)
            entries = []
            for f in files:
                patch = f.get("patch")
                if patch is None:
                    body = "blob:" + str(f.get("sha"))
                else:
                    body = "\n".join(
                        line for line in patch.split("\n") if not line.startswith("@@")
                    )
                entries.append([f["filename"], body])
        except (json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError):
            return ReadFailure(-1, "could not parse gh api compare JSON for the diff signature")
        entries.sort()
        return hashlib.sha256(json.dumps(entries).encode("utf-8")).hexdigest()

    def check_runs(self, pr: str, sha: str) -> Union[Tuple[CheckRun, ...], ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, _number = parts
        rows = self._gh_api_lines(
            "/repos/%s/%s/commits/%s/check-runs?per_page=100" % (owner, repo, sha),
            ".total_count as $total | .check_runs[] | "
            "{name,status,conclusion,started_at,completed_at,url:.html_url,total:$total}",
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
        workflows = self._workflow_names(owner, repo, sha, data)
        return tuple(
            CheckRun(
                workflow=workflows.get(_actions_run_id(c.get("url") or ""), ("", ""))[0],
                workflow_file=workflows.get(_actions_run_id(c.get("url") or ""), ("", ""))[1],
                name=c.get("name") or "",
                status=c.get("status") or "",
                conclusion=c.get("conclusion"),
                url=c.get("url") or "",
                started_at=_parse_iso(c["started_at"]) if c.get("started_at") else 0.0,
                completed_at=_parse_iso(c["completed_at"]) if c.get("completed_at") else 0.0,
            )
            for c in data
        )

    def _workflow_names(self, owner, repo, sha, data):
        if not any(_actions_run_id(c.get("url") or "") for c in data):
            return {}
        rows = self._gh_api_lines(
            "/repos/%s/%s/actions/runs?head_sha=%s&per_page=100" % (owner, repo, sha),
            ".workflow_runs[] | {id,name,path}",
            paginate=True,
        )
        if isinstance(rows, ReadFailure):
            return {}
        names = {}
        for r in rows:
            if not isinstance(r, dict) or r.get("id") is None:
                continue
            base = os.path.basename(r.get("path") or "")
            name = r.get("name") or os.path.splitext(base)[0]
            if name or base:
                names[str(r["id"])] = (name, base)
        return names

    def workflow_sources(self, pr: str, sha: str) -> Union[Tuple[WorkflowFile, ...], ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, _number = parts
        directory = "repos/%s/%s/contents/.github/workflows" % (owner, repo)
        try:
            listing = subprocess.run(
                ["gh", "api", "%s?ref=%s" % (directory, sha),
                 "--jq", '[.[]? | select(.type=="file") | .name]'],
                capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return _timeout_read_failure()
        if listing.returncode != 0:
            if "404" in listing.stderr or "Not Found" in listing.stderr:
                return ()
            return ReadFailure(listing.returncode, listing.stderr)
        try:
            names = json.loads(listing.stdout)
        except (json.JSONDecodeError, ValueError):
            return ReadFailure(-1, "could not parse gh api JSON for the workflow listing")
        files = []
        for name in names:
            if not name.endswith((".yml", ".yaml")):
                continue
            try:
                raw = subprocess.run(
                    ["gh", "api", "-H", "Accept: application/vnd.github.raw",
                     "%s/%s?ref=%s" % (directory, name, sha)],
                    capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                files.append(WorkflowFile(name, None))
                continue
            files.append(WorkflowFile(name, raw.stdout if raw.returncode == 0 else None))
        return tuple(files)

    def workflow_runs(self, pr: str, sha: str) -> Union[int, ReadFailure]:
        parts = _repo_parts(pr)
        if not parts:
            return ReadFailure(-1, "pr is not a parseable GitHub PR URL: %r" % pr)
        owner, repo, _number = parts
        total = 0
        for event in ("pull_request", "pull_request_target"):
            try:
                r = subprocess.run(
                    ["gh", "api",
                     "repos/%s/%s/actions/runs?head_sha=%s&event=%s" % (owner, repo, sha, event),
                     "--jq", ".total_count"],
                    capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                return _timeout_read_failure()
            if r.returncode != 0:
                return ReadFailure(r.returncode, r.stderr)
            try:
                total += int(r.stdout.strip())
            except ValueError:
                return ReadFailure(-1, "could not parse gh api total_count for workflow runs")
        return total

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
        login = r.stdout.strip()
        if not login:
            return ReadFailure(-1, "gh returned no login")
        return login

    def pr_sync_state(self, pr: str) -> Union[PrSync, ReadFailure]:
        view = self.pr_view(pr)
        if isinstance(view, ReadFailure):
            return view
        return PrSync(
            behind=view.merge_state_status == "BEHIND",
            conflicted=view.mergeable == "CONFLICTING" or view.merge_state_status == "DIRTY",
            head_sha=view.head_sha,
            base_key=view.base_key,
            settled=view.mergeable != "UNKNOWN" and view.merge_state_status != "UNKNOWN",
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

    def stack_view(self, stack_url: str) -> Union[Tuple[StackLayer, ...], ReadFailure]:
        m = _STACK_URL_RE.match(stack_url)
        if not m:
            return ReadFailure(-1, "stack is not a parseable GitHub stack URL: %r" % stack_url)
        owner, repo, number = m.groups()
        data = self._gh_api_json("repos/%s/%s/stacks/%s" % (owner, repo, number))
        if isinstance(data, ReadFailure):
            return data
        try:
            stack_base = data["base"]["ref"]
            entries = data["pull_requests"]
            layers = []
            below_head = None
            for entry in entries:
                state = "merged" if entry.get("merged_at") else entry["state"]
                layers.append(StackLayer(
                    number=entry["number"],
                    url="https://github.com/%s/%s/pull/%s" % (owner, repo, entry["number"]),
                    head_ref=entry["head"]["ref"],
                    base_ref=below_head if below_head is not None else stack_base,
                    head_sha=entry["head"]["sha"],
                    state=state,
                ))
                if state != "merged":
                    below_head = entry["head"]["ref"]
        except (KeyError, TypeError, AttributeError):
            return ReadFailure(-1, "could not parse gh stack JSON for %s" % stack_url)
        return tuple(layers)

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
            ".[] | {url: .pull_request_url}",
            paginate=True,
        )
        if isinstance(rows, ReadFailure):
            return rows
        urls = set()
        for row in rows:
            m = _PULL_API_URL_RE.search(row.get("url") or "")
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
        owner, repo, number = parts
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
        api_head = data.get("headRefOid") or ""
        fresh_head = self._fresh_head_sha(owner, repo, number)
        head = fresh_head or api_head
        mergeable = data.get("mergeable") or ""
        merge_state_status = data.get("mergeStateStatus") or ""
        if fresh_head and fresh_head != api_head:
            mergeable = "UNKNOWN"
            merge_state_status = "UNKNOWN"
        return PrView(
            state=data.get("state") or "",
            head_sha=head,
            base_ref=base,
            base_key="%s/%s@%s" % (owner, repo, base),
            mergeable=mergeable,
            merge_state_status=merge_state_status,
            updated_at=updated,
        )
