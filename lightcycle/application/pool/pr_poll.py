from dataclasses import replace

from lightcycle.application.pool.pr_snapshot import PrEntry
from lightcycle.domain.pool import pr_repo
from lightcycle.ports.github import ReadFailure

def _listed_state(listed):
    if listed.state == "closed":
        return "MERGED" if listed.merged else "CLOSED"
    return "OPEN"


class PrPoll:
    def __init__(self, github, snapshot, writes):
        self._github = github
        self._snapshot = snapshot
        self._writes = writes
        self._cutoffs = {}
        self._tips = {}

    def run(self, wanted):
        self._writes.perform(self._github)
        by_repo = {}
        for pr in sorted(wanted.prs):
            repo = pr_repo(pr)
            if repo is not None:
                by_repo.setdefault(repo, []).append(pr)
        failed = set()
        for repo, prs in by_repo.items():
            failed |= self._poll_repo(repo, prs)
        self._compare_files(wanted.files)
        self._read_checks(wanted.checks)
        self._snapshot.retain(wanted.prs)
        self._writes.retain(wanted.prs)

    def _poll_repo(self, repo, prs):
        cutoff = self._cutoffs.get(repo)
        listed = {}
        inline = frozenset()
        failed = set()
        if cutoff is not None:
            rows = self._github.list_prs(repo, cutoff)
            comments = self._github.repo_inline_comments(repo, cutoff)
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
                    or (row is not None and row.updated_at != entry.updated_at)):
                moved.append(pr)
            else:
                unmoved.append(pr)
        base_moved = self._base_moved(repo, unmoved)
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
        for pr in base_moved:
            if not self._refresh_view(pr):
                failed.add(pr)
        if cutoff is None:
            self._record_tips(repo, prs)
        if cutoff is None and views_newest is not None:
            self._cutoffs[repo] = views_newest
        elif cutoff is not None and not failed:
            self._cutoffs[repo] = newest
        return failed

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
                continue
            previous = self._tips.get((repo, base))
            self._tips[(repo, base)] = tip
            if previous is not None and previous != tip:
                moved.extend(prs)
        return moved

    def _record_tips(self, repo, prs):
        bases = set()
        for pr in prs:
            entry = self._snapshot.entry_of(pr)
            if entry is not None and entry.view is not None:
                bases.add(entry.view.base_ref)
        for base in bases:
            tip = self._github.branch_tip(repo, base)
            if not isinstance(tip, ReadFailure):
                self._tips[(repo, base)] = tip

    def _refresh_view(self, pr):
        view = self._github.pr_view(pr)
        if isinstance(view, ReadFailure):
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
            self._snapshot.mark_stale(pr)
            return None
        previous = self._snapshot.entry_of(pr) or PrEntry()
        entry = replace(previous, state=view.state, view=view, updated_at=view.updated_at)
        self._snapshot.publish(pr, entry)
        push_time = self._github.last_push_time(pr)
        comments = self._github.comments_since(pr, 0.0)
        pulls = self._github.pull_comments(pr, 0.0)
        reviews = self._github.reviews(pr, 0.0)
        reads = (push_time, comments, pulls, reviews)
        if any(isinstance(r, ReadFailure) for r in reads):
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
                continue
            view = self._github.pr_view(pr)
            if isinstance(view, ReadFailure):
                continue
            current = self._snapshot.entry_of(pr) or entry
            self._snapshot.publish(pr, replace(current, state=view.state, view=view))
            if view.head_sha == sha:
                self._snapshot.publish_checks(pr, sha, runs)
