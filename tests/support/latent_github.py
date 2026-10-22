import functools

from lightcycle.ports.github import GitHubEventsPort, ReadFailure
from tests.support.fake_github import FakeGitHub

_TIMEOUT = ReadFailure(-1, "gh timed out after 60s")
_BOOM = ReadFailure(1, "boom")


class _Appearance:
    def __init__(self, payload, due, after_reads):
        self.payload = payload
        self.due = due
        self.after_reads = after_reads
        self.reads = 0


class LatentGitHub(FakeGitHub):
    def __init__(self, clock, **kwargs):
        super().__init__(**kwargs)
        self._clock = clock
        self._check_schedule = {}
        self._run_schedule = {}
        self._run_counts = {}
        self._failures = []
        self._read_seconds = {}
        self.counts = {}
        self._per_pr_counts = {}
        for name in GitHubEventsPort.__abstractmethods__:
            setattr(self, name, self._wrap(name, getattr(self, name)))

    def _wrap(self, name, original):
        @functools.wraps(original)
        def wrapper(*args, **kwargs):
            self.counts[name] = self.counts.get(name, 0) + 1
            self._release_due(name, args)
            self._clock.advance(self._read_seconds.get(name, 0.0))
            scripted = self._scripted_failure(name, args, kwargs)
            if scripted is not None:
                return scripted
            return original(*args, **kwargs)

        return wrapper

    def _release_due(self, name, args):
        if name == "check_runs" and len(args) >= 2:
            appearance = self._check_schedule.get((args[0], args[1]))
            if appearance is not None:
                appearance.reads += 1
                if self._is_due(appearance):
                    self._check_runs_by_sha[(args[0], args[1])] = appearance.payload
                    del self._check_schedule[(args[0], args[1])]
        if name == "workflow_runs" and len(args) >= 2:
            appearance = self._run_schedule.get((args[0], args[1]))
            if appearance is not None:
                appearance.reads += 1
                if self._is_due(appearance):
                    self._run_counts[(args[0], args[1])] = appearance.payload
                    del self._run_schedule[(args[0], args[1])]

    def _is_due(self, appearance):
        return self._clock() >= appearance.due and appearance.reads > appearance.after_reads

    def _scripted_failure(self, name, args, kwargs):
        for failure in self._failures:
            if failure["method"] != name:
                continue
            pr = failure["pr"]
            if pr is not None and pr not in args and pr not in kwargs.values():
                continue
            key = (name, pr)
            self._per_pr_counts[key] = self._per_pr_counts.get(key, 0) + 1
            if self._per_pr_counts[key] in failure["on"]:
                return failure["result"]
        return None

    def push(self, pr, sha):
        self._head_shas[pr] = sha
        self._updated_ats[pr] = self._clock()

    def merge(self, pr):
        self._merged.add(pr)
        self._updated_ats[pr] = self._clock()

    def check_runs_appear(self, pr, sha, runs, after_seconds=0.0, after_reads=0):
        self._check_runs_by_sha.pop((pr, sha), None)
        self._check_schedule[(pr, sha)] = _Appearance(
            tuple(runs), self._clock() + after_seconds, after_reads)

    def workflow_run_appears(self, pr, sha, count=1, after_seconds=0.0, after_reads=0):
        self._run_counts.pop((pr, sha), None)
        self._run_schedule[(pr, sha)] = _Appearance(
            count, self._clock() + after_seconds, after_reads)

    def workflow_runs(self, pr, sha):
        self._record("workflow_runs", pr, sha)
        if "workflow_runs" in self._failing_calls:
            return _BOOM
        return self._run_counts.get((pr, sha), 0)

    def fail_call(self, method, on=(1,), pr=None, failure=_BOOM):
        self._failures.append({"method": method, "on": tuple(on), "pr": pr, "result": failure})

    def time_out_call(self, method, on=(1,), pr=None):
        self.fail_call(method, on=on, pr=pr, failure=_TIMEOUT)

    def read_takes(self, method, seconds):
        self._read_seconds[method] = seconds
