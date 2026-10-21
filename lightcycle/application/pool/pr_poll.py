import time
import zlib
from dataclasses import replace

from lightcycle.application.pool.pr_snapshot import PrEntry
from lightcycle.domain.pool import pr_repo
from lightcycle.ports.github import ReadFailure

def _unsettled(view):
    return view.state == "OPEN" and "UNKNOWN" in (view.mergeable, view.merge_state_status)


def _listed_state(listed):
    if listed.state == "closed":
        return "MERGED" if listed.merged else "CLOSED"
    return "OPEN"


class PrPoll:
    def __init__(self, github, snapshot, writes, worker_log):
        self._github = github
        self._snapshot = snapshot
        self._writes = writes
        self._worker_log = worker_log
        self._now = 0.0
        self._cutoffs = {}
        self._tips = {}
        self._runs = 0

    def _log_failure(self, read, target, failure):
        detail = failure.stderr.strip().splitlines()[0] if failure.stderr.strip() else ""
        message = "%s %s failed (exit %s)" % (read, target, failure.returncode)
        if detail:
            message += ": " + detail
        self._worker_log.append_run_log("%s  %-7s  %s\n" % (
            time.strftime("%H:%M:%S", time.localtime(self._now)), "github", message))

    def run(self, wanted, now, refresh_polls):
        self._now = now
        self._writes.perform(self._github)
        by_repo = {}
        for pr in sorted(wanted.prs):
            repo = pr_repo(pr)
            if repo is not None:
                by_repo.setdefault(repo, []).append(pr)
        failed = set()
        for repo, prs in by_repo.items():
            repo_failed = self._poll_repo(repo, prs, refresh_polls)
            failed |= repo_failed
            self._snapshot.confirm([pr for pr in prs if pr not in repo_failed], wanted.epoch)
        self._compare_files(wanted.files)
        self._read_checks(wanted.checks)
        self._snapshot.retain(wanted.prs, wanted.checks)
        self._writes.retain(wanted.prs)
        self._runs += 1

    def _poll_repo(self, repo, prs, refresh_polls):
        cutoff = self._cutoffs.get(repo)
        listed = {}
        inline = frozenset()
        failed = set()
        if cutoff is not None:
            rows = self._github.list_prs(repo, cutoff)
            comments = self._github.repo_inline_comments(repo, cutoff)
            if isinstance(rows, ReadFailure):
                self._log_failure("list_prs", repo, rows)
            if isinstance(comments, ReadFailure):
                self._log_failure("repo_inline_comments", repo, comments)
            if isinstance(rows, ReadFailure) or isinstance(comments, ReadFailure):
                for pr in prs:
                    self._snapshot.mark_stale(pr)
                return set(prs)
            listed = {row.url: row for row in rows}
            inline = comments
        newest = max([row.updated_at for row in listed.values()] + [cutoff or 0.0])
        views_newest = None
        moved, unmoved = [], []
        for pr in prs:
            entry = self._snapshot.entry_of(pr)
            row = listed.get(pr)
            if (entry is None or entry.stale or cutoff is None or pr in inline
                    or (row is not None and (row.updated_at != entry.updated_at
                                             or _listed_state(row) != entry.state))):
                moved.append(pr)
            else:
                unmoved.append(pr)
        base_moved = self._base_moved(repo, unmoved)
        for pr in unmoved:
            if pr not in base_moved and self._needs_reread(pr, refresh_polls):
                base_moved.append(pr)
        baselined = {}
        for pr in moved:
            row = listed.get(pr)
            if row is not None and row.state == "closed":
                self._classify_closed(pr, row)
                continue
            seen = self._read_in_full(pr)
            if seen is None:
                failed.add(pr)
            elif views_newest is None or seen > views_newest:
                views_newest = seen
            if seen is not None and cutoff is None:
                self._baseline_tip(repo, pr, baselined)
        base_moved.extend(baselined.values())
        for pr in base_moved:
            if not self._refresh_view(pr):
                failed.add(pr)
        if cutoff is None and views_newest is not None:
            self._cutoffs[repo] = views_newest
        elif cutoff is not None and not failed:
            self._cutoffs[repo] = newest
        return failed

    def _needs_reread(self, pr, refresh_polls):
        entry = self._snapshot.entry_of(pr)
        if entry is not None and entry.view is not None and _unsettled(entry.view):
            return True
        return (self._runs + zlib.crc32(pr.encode())) % refresh_polls == 0

    def _classify_closed(self, pr, row):
        entry = self._snapshot.entry_of(pr) or PrEntry()
        self._snapshot.publish(
            pr, replace(entry, state=_listed_state(row), updated_at=row.updated_at, stale=False)
        )

    def _base_moved(self, repo, unmoved):
        bases = {}
        for pr in unmoved:
            entry = self._snapshot.entry_of(pr)
            if entry is not None and entry.view is not None:
                bases.setdefault(entry.view.base_ref, []).append(pr)
        moved = []
        for base, prs in bases.items():
            tip = self._github.branch_tip(repo, base)
            if isinstance(tip, ReadFailure):
                self._log_failure("branch_tip", "%s@%s" % (repo, base), tip)
                continue
            previous = self._tips.get((repo, base))
            self._tips[(repo, base)] = tip
            if previous is not None and previous != tip:
                moved.extend(prs)
        return moved

    def _baseline_tip(self, repo, pr, baselined):
        entry = self._snapshot.entry_of(pr)
        if entry is None or entry.view is None:
            return
        base = entry.view.base_ref
        if base in baselined:
            return
        tip = self._github.branch_tip(repo, base)
        if isinstance(tip, ReadFailure):
            self._log_failure("branch_tip", "%s@%s" % (repo, base), tip)
            return
        self._tips[(repo, base)] = tip
        baselined[base] = pr

    def _refresh_view(self, pr):
        view = self._github.pr_view(pr)
        if isinstance(view, ReadFailure):
            self._log_failure("pr_view", pr, view)
            self._snapshot.mark_stale(pr)
            return False
        entry = self._snapshot.entry_of(pr) or PrEntry()
        self._snapshot.publish(
            pr, replace(entry, state=view.state, view=view, updated_at=view.updated_at)
        )
        return True

    def _read_in_full(self, pr):
        view = self._github.pr_view(pr)
        if isinstance(view, ReadFailure):
            self._log_failure("pr_view", pr, view)
            self._snapshot.mark_stale(pr)
            return None
        previous = self._snapshot.entry_of(pr) or PrEntry()
        entry = replace(previous, state=view.state, view=view, updated_at=view.updated_at)
        self._snapshot.publish(pr, entry)
        push_time = self._github.last_push_time(pr)
        comments = self._github.comments_since(pr, 0.0)
        pulls = self._github.pull_comments(pr, 0.0)
        reviews = self._github.reviews(pr, 0.0)
        reads = (
            ("last_push_time", push_time), ("comments_since", comments),
            ("pull_comments", pulls), ("reviews", reviews),
        )
        failures = [(name, r) for name, r in reads if isinstance(r, ReadFailure)]
        for name, failure in failures:
            self._log_failure(name, pr, failure)
        if failures:
            self._snapshot.mark_stale(pr)
            return None
        self._snapshot.publish(
            pr,
            replace(
                entry, push_time=push_time, comments=comments, pull_comments=pulls,
                reviews=reviews, stale=False,
            ),
        )
        return view.updated_at

    def _compare_files(self, wanted_files):
        for pr, sha in sorted(wanted_files):
            if self._snapshot.known_files(pr, sha):
                continue
            entry = self._snapshot.entry_of(pr)
            if entry is None or entry.view is None:
                continue
            files = self._github.changed_files(pr, sha, entry.view.base_ref)
            if isinstance(files, ReadFailure):
                self._log_failure("changed_files", pr, files)
                continue
            self._snapshot.publish_files(pr, sha, files)

    def _read_checks(self, wanted_checks):
        for pr in sorted(wanted_checks):
            entry = self._snapshot.entry_of(pr)
            if entry is None or entry.view is None:
                continue
            sha = entry.view.head_sha
            runs = self._github.check_runs(pr, sha)
            if isinstance(runs, ReadFailure):
                self._log_failure("check_runs", pr, runs)
                continue
            view = self._github.pr_view(pr)
            if isinstance(view, ReadFailure):
                self._log_failure("pr_view", pr, view)
                continue
            required = self._writes.required_checks(self._github, view.base_key)
            if not isinstance(required, ReadFailure):
                self._snapshot.publish_required(view.base_key, required)
            current = self._snapshot.entry_of(pr) or entry
            self._snapshot.publish(pr, replace(current, state=view.state, view=view))
            if view.head_sha == sha:
                self._snapshot.publish_checks(pr, sha, runs)
