import unittest

from lightcycle.application.pool.github_poll import GithubPollUseCase
from lightcycle.application.pool.no_op_gates import NoOpMonitor
from lightcycle.application.pool.pr_snapshot import PrSnapshot
from lightcycle.application.pool.tick import TickInput
from lightcycle.ports.github import CheckRun, Comment, NotYetRead, ReadFailure, Review
from tests.support.fake_github import FakeGitHub
from tests.support.fake_github_poll_runner import BlockingGithubPollRunner, InlineGithubPollRunner
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.unit.test_pool import FakeSpawner, make_tick
from tests.unit.test_tick_lifecycle_gate import _Config as _BaseConfig, _Reload

_PR = "https://github.com/acme/widget/pull/1"
_OTHER = "https://github.com/acme/widget/pull/2"
_POLL = 60
_TICK = 5


class _Config(_BaseConfig):
    def poll_seconds(self):
        return _TICK

    def github_poll_seconds(self):
        return _POLL


class _Exploding(FakeGitHub):
    def pr_view(self, pr):
        raise AssertionError("the tick must not read GitHub")

    def list_prs(self, repo, cutoff):
        raise AssertionError("the tick must not read GitHub")


class _ProbeMonitor:
    def __init__(self, snapshot, probe):
        self._snapshot = snapshot
        self._probe = probe
        self.reads = []

    def execute(self):
        self.reads.append(self._probe(self._snapshot))
        return NoOpMonitor().execute()


def _tick(monitor, gate):
    return make_tick(
        FakeStore(), FakeWorkers(), FakeSpawner(), _Config(),
        monitor=monitor, github_poll_gate=gate, config_reload=_Reload("unchanged"))


def _gate(snapshot, github, runner):
    return GithubPollUseCase(snapshot, github, runner, _Config())


class TestTickIndependence(unittest.TestCase):
    def test_a_poll_that_never_returns_does_not_stop_the_tick(self):
        github = _Exploding(updated_ats={_PR: 1.0})
        snapshot = PrSnapshot(github)
        runner = BlockingGithubPollRunner()
        monitor = _ProbeMonitor(snapshot, lambda s: s.pr_sync_state(_PR))
        tick = _tick(monitor, _gate(snapshot, github, runner))

        responses = [tick.execute(TickInput(now=float(n * _TICK))) for n in range(30)]

        self.assertEqual(len(responses), 30)
        self.assertEqual(len(monitor.reads), 30)
        self.assertEqual(runner.starts, 1)
        self.assertTrue(all(isinstance(r, NotYetRead) for r in monitor.reads))
        self.assertEqual(github.calls, [])


class TestColdStart(unittest.TestCase):
    def test_tick_one_polls_the_prs_its_monitor_registered_and_tick_two_acts(self):
        github = FakeGitHub(merged_prs=[_PR], updated_ats={_PR: 1.0})
        snapshot = PrSnapshot(github)
        runner = InlineGithubPollRunner()
        monitor = _ProbeMonitor(snapshot, lambda s: s.is_merged(_PR))
        tick = _tick(monitor, _gate(snapshot, github, runner))

        tick.execute(TickInput(now=0.0))
        self.assertIsInstance(monitor.reads[0], NotYetRead)
        self.assertEqual(runner.starts, 1)
        self.assertEqual(snapshot.entry_of(_PR).state, "MERGED")

        tick.execute(TickInput(now=float(_TICK)))
        self.assertIs(monitor.reads[1], True)
        self.assertEqual(runner.starts, 1)
        names = [c[0] for c in github.calls]
        self.assertNotIn("list_prs", names)
        self.assertNotIn("repo_inline_comments", names)
        self.assertEqual(names.count("pr_view"), 1)

    def test_a_pool_with_no_gated_prs_starts_nothing_until_one_arrives(self):
        github = FakeGitHub()
        snapshot = PrSnapshot(github)
        runner = InlineGithubPollRunner()
        watching = []
        monitor = _ProbeMonitor(snapshot, lambda s: [s.pr_sync_state(p) for p in watching])
        tick = _tick(monitor, _gate(snapshot, github, runner))

        tick.execute(TickInput(now=0.0))
        tick.execute(TickInput(now=float(_TICK)))
        self.assertEqual(runner.starts, 0)

        watching.append(_PR)
        tick.execute(TickInput(now=2.0 * _TICK))
        self.assertEqual(runner.starts, 1)


def _push(github):
    github._head_shas[_PR] = "moved"
    github.touch(_PR, 200.0)


def _merge(github):
    github._merged.add(_PR)
    github.touch(_PR, 200.0)


def _behind(github):
    github._behind.add(_PR)
    github.touch(_PR, 200.0)


def _conflict(github):
    github._conflicted.add(_PR)
    github.touch(_PR, 200.0)


def _review(github):
    github._timed_reviews.append((200.0, Review(author="r", body="x", created_at=200.0, id="1")))
    github.touch(_PR, 200.0)


def _top_level(github):
    github._timed_comments.append(
        (200.0, Comment(author="r", body="x", is_top_level=True, id="2", created_at=200.0)))
    github.touch(_PR, 200.0)


def _inline_only(github):
    github._timed_comments.append(
        (200.0, Comment(author="r", body="x", is_top_level=False, id="3", created_at=200.0)))
    github.inline_comment_on(_PR, 200.0)


def _base_advance_only(github):
    github._behind.add(_PR)
    github.advance_base("acme/widget", "main")


def _ci(github):
    github._check_runs_by_sha[(_PR, "h0")] = (CheckRun("ci", "completed", "success"),)


_EVENTS = {
    "head move": (_push, lambda s: s.head_sha(_PR) == "moved"),
    "merge": (_merge, lambda s: s.is_merged(_PR) is True),
    "behind-main": (_behind, lambda s: _flag(s.pr_sync_state(_PR), "behind")),
    "conflict": (_conflict, lambda s: _flag(s.pr_sync_state(_PR), "conflicted")),
    "review": (_review, lambda s: _nonempty(s.reviews(_PR, 0.0))),
    "top-level mention": (_top_level, lambda s: _nonempty(s.comments_since(_PR, 0.0))),
    "inline comment": (_inline_only, lambda s: _nonempty(s.pull_comments(_PR, 0.0))),
    "behind-main with no updated_at change": (
        _base_advance_only, lambda s: _flag(s.pr_sync_state(_PR), "behind")),
    "ci success": (_ci, lambda s: _ci_done(s.check_runs(_PR, "h0"))),
}


def _flag(sync, name):
    return not isinstance(sync, ReadFailure) and getattr(sync, name)


def _nonempty(items):
    return not isinstance(items, ReadFailure) and bool(items)


def _ci_done(runs):
    return not isinstance(runs, ReadFailure) and any(r.conclusion == "success" for r in runs)


class TestLatency(unittest.TestCase):
    def test_each_event_on_a_watched_pr_is_seen_within_one_poll_interval_plus_a_tick(self):
        for name, (event, seen) in _EVENTS.items():
            with self.subTest(event=name):
                github = FakeGitHub(
                    updated_ats={_PR: 100.0, _OTHER: 100.0}, head_shas={_PR: "h0", _OTHER: "h0"})
                snapshot = PrSnapshot(github)
                monitor = _ProbeMonitor(snapshot, seen)
                tick = _tick(monitor, _gate(snapshot, github, InlineGithubPollRunner()))

                happened_at = 7.0
                noticed_at = None
                fired = False
                for n in range(0, 40):
                    now = float(n * _TICK)
                    if not fired and now >= happened_at:
                        event(github)
                        fired = True
                    snapshot.pr_sync_state(_OTHER)
                    tick.execute(TickInput(now=now))
                    if fired and monitor.reads[-1] is True and noticed_at is None:
                        noticed_at = now
                self.assertIsNotNone(noticed_at)
                self.assertLessEqual(noticed_at - happened_at, _POLL + _TICK)


if __name__ == "__main__":
    unittest.main()


class TestPrime(unittest.TestCase):
    def test_prime_registers_polls_and_lets_the_next_tick_act(self):
        github = FakeGitHub(merged_prs=[_PR], updated_ats={_PR: 1.0})
        snapshot = PrSnapshot(github)
        runner = InlineGithubPollRunner()
        monitor = _ProbeMonitor(snapshot, lambda s: s.is_merged(_PR))
        tick = _tick(monitor, _gate(snapshot, github, runner))

        tick.prime(0.0)
        tick.execute(TickInput(now=0.0))

        self.assertIsInstance(monitor.reads[0], NotYetRead)
        self.assertIs(monitor.reads[1], True)
        self.assertEqual(runner.starts, 1)
