import time
import unittest

from lightcycle.application.flow.complete_step import CompleteStepUseCase
from lightcycle.application.pool import MonitorPrsUseCase
from lightcycle.application.pool.github_poll import GithubPollUseCase
from lightcycle.application.pool.no_op_gates import NoOpMonitor
from lightcycle.application.pool.pr_snapshot import PrSnapshot
from lightcycle.application.pool.pr_writes import PrWrites
from lightcycle.application.pool.resolve_ci import ResolveCiUseCase
from lightcycle.application.pool.tick import TickInput
from lightcycle.ports.github import CheckRun, Comment, NotYetRead, ReadFailure, Review
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_github import FakeGitHub
from tests.support.fake_github_budget_status import FakeGithubBudgetStatus
from tests.support.fake_github_poll_runner import BlockingGithubPollRunner, InlineGithubPollRunner
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.unit.test_monitor_prs import FakeWorktrees
from tests.unit.test_pool import FakeSpawner, make_tick
from tests.unit.test_resolve_ci import _FLOW, _FlowAdapter, plant_pr
from tests.unit.test_update_behind_prs import _BASE, _FLOW as _BEHIND_FLOW
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

    def github_view_refresh_polls(self):
        return 10


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
    return GithubPollUseCase(snapshot, github, runner, _Config(), PrWrites(time.monotonic), FakeGithubBudgetStatus(), time.time, FakeFs())


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


class _CiMonitor:
    def __init__(self, resolve):
        self._resolve = resolve

    def execute(self):
        self._resolve.execute()
        return NoOpMonitor().execute()


class TestCiStageIssuesNoGitCall(unittest.TestCase):
    def test_a_tick_with_a_ci_step_and_a_poll_that_never_returns_runs_no_git_fetch(self):
        github = _Exploding(updated_ats={_PR: 1.0}, head_shas={_PR: "sha1"})
        snapshot = PrSnapshot(github)
        store = FakeStore()
        item = store.create_item("building a thing", "a description")
        plant_pr(store, item, _PR, branch="feat/thing")
        step = store.create_step(step="poll-ci", role="engine", parent=item)
        flow = _FlowAdapter(_FLOW)
        monitor = _CiMonitor(ResolveCiUseCase(store, snapshot, flow, CompleteStepUseCase(store, flow), clock=time.monotonic, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, wall_clock=lambda: 10000.0, views=snapshot))
        git = FakeGit()
        tick = make_tick(
            store, FakeWorkers(), FakeSpawner(), _Config(), monitor=monitor,
            github_poll_gate=_gate(snapshot, github, BlockingGithubPollRunner()),
            config_reload=_Reload("unchanged"), git=git)

        for n in range(3):
            tick.execute(TickInput(now=float(n * _TICK)))

        self.assertEqual([c for c in git.calls if "fetch" in c[0]], [])
        self.assertEqual(store.get_node(step).state.value, "queued")


def _ci_pool(hold_view):
    github = FakeGitHub(
        updated_ats={_PR: 100.0},
        head_shas={_PR: "sha1"},
        check_runs_by_sha={(_PR, "sha1"): (CheckRun("ci", "completed", "success"),)})
    snapshot = PrSnapshot(github)
    store = FakeStore()
    item = store.create_item("building a thing", "a description")
    plant_pr(store, item, _PR, branch="feat/thing")
    flow = _FlowAdapter(_FLOW)
    monitor = _CiMonitor(ResolveCiUseCase(store, snapshot, flow, CompleteStepUseCase(store, flow), clock=time.monotonic, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, wall_clock=lambda: 10000.0, views=snapshot))
    tick = make_tick(
        store, FakeWorkers(), FakeSpawner(), _Config(), monitor=monitor,
        github_poll_gate=_gate(snapshot, github, InlineGithubPollRunner()),
        config_reload=_Reload("unchanged"))
    return store, item, snapshot, tick


def _judged_at(hold_view, created_at):
    store, item, snapshot, tick = _ci_pool(hold_view)
    step = None
    for n in range(0, 80):
        now = float(n * _TICK)
        if hold_view:
            snapshot.pr_sync_state(_PR)
        if step is None and now >= created_at:
            step = store.create_step(step="poll-ci", role="engine", parent=item)
        tick.execute(TickInput(now=now))
        if step is not None and store.get_node(step).state.value == "done":
            return store, step, snapshot, now
    raise AssertionError("poll-ci was never judged")


class TestCiJudgementLatency(unittest.TestCase):
    def test_a_pr_with_a_held_view_is_judged_within_one_poll_interval_plus_a_tick(self):
        _, _, _, judged_at = _judged_at(True, 7.0)

        self.assertLessEqual(judged_at - 7.0, _POLL + _TICK)

    def test_a_pr_with_no_view_yet_needs_the_second_poll(self):
        _, _, _, judged_at = _judged_at(False, 7.0)

        self.assertGreater(judged_at - 7.0, _POLL + _TICK)
        self.assertLessEqual(judged_at - 7.0, 2 * _POLL + _TICK)


class TestCiJudgementAnchor(unittest.TestCase):
    def test_the_judged_sha_and_the_note_equal_the_head_detect_head_moved_compares(self):
        store, step, snapshot, _ = _judged_at(True, 7.0)

        compared = snapshot.pr_sync_state(_PR).head_sha
        judged = [a.value for a in store.item_artifacts(step) if a.type == "ci-judged-sha"]

        self.assertEqual(judged, [compared])
        self.assertEqual(compared, "sha1")
        self.assertIn(compared, store.get_node(step).report)


def _conflicted_then_rebased(github):
    github._conflicted.add(_PR)
    github.touch(_PR, 150.0)


def _rework_push(github):
    github._head_shas[_PR] = "sha1"
    github._check_runs_by_sha[(_PR, "sha1")] = (CheckRun("ci", "in_progress", None),)
    github.touch(_PR, 200.0)


def _rebase_clears_conflict(github):
    github._conflicted.discard(_PR)
    github._head_shas[_PR] = "sha1"
    github._check_runs_by_sha[(_PR, "sha1")] = (CheckRun("ci", "in_progress", None),)
    github.touch(_PR, 200.0)


def _head_change_pool(before_move, settle=True):
    github = FakeGitHub(
        updated_ats={_PR: 100.0},
        head_shas={_PR: "sha0"},
        check_runs_by_sha={(_PR, "sha0"): (CheckRun("ci", "completed", "success"),)})
    snapshot = PrSnapshot(github)
    store = FakeStore()
    item = store.create_item("building a thing", "a description")
    plant_pr(store, item, _PR, branch="feat/thing")
    flow = _FlowAdapter(_FLOW)
    monitor = _CiMonitor(ResolveCiUseCase(
        store, snapshot, flow, CompleteStepUseCase(store, flow),
        clock=time.monotonic, poll_seconds=lambda: _POLL,
        ci_ceiling_seconds=lambda: 3600, wall_clock=lambda: 10000.0, views=snapshot))
    tick = make_tick(
        store, FakeWorkers(), FakeSpawner(), _Config(), monitor=monitor,
        github_poll_gate=_gate(snapshot, github, InlineGithubPollRunner()),
        config_reload=_Reload("unchanged"))
    clock = [0.0]

    def run(seconds, hold=True):
        end = clock[0] + seconds
        while clock[0] < end:
            if hold:
                snapshot.pr_sync_state(_PR)
            tick.execute(TickInput(now=clock[0]))
            clock[0] += _TICK

    first = store.create_step(step="poll-ci", role="engine", parent=item)
    run(_POLL + 2 * _TICK)
    assert store.get_node(first).state.value == "done"
    for event in before_move:
        event(github)
        if settle:
            run(_POLL + _TICK)
    return github, store, item, snapshot, run, clock


class TestCiJudgementAfterHeadChange(unittest.TestCase):
    def _assert_judged_on_new_head(self, before_move):
        github, store, item, snapshot, run, clock = _head_change_pool(before_move)
        second = store.create_step(step="poll-ci", role="engine", parent=item)
        run(3 * _TICK)
        self.assertEqual(store.get_node(second).state.value, "queued")

        github._check_runs_by_sha[(_PR, "sha1")] = (CheckRun("ci", "completed", "success"),)
        github.touch(_PR, clock[0])
        concluded_at = clock[0]
        judged_at = None
        while clock[0] <= concluded_at + 4 * _POLL:
            run(_TICK)
            if store.get_node(second).state.value == "done":
                judged_at = clock[0] - _TICK
                break

        self.assertIsNotNone(judged_at)
        self.assertLessEqual(judged_at - concluded_at, _POLL + _TICK)
        judged = [a.value for a in store.item_artifacts(second) if a.type == "ci-judged-sha"]
        self.assertEqual(judged, ["sha1"])
        self.assertIn("sha1", store.get_node(second).report)
        self.assertIn((_PR, "sha0"), github._check_runs_by_sha)

    def test_a_conflict_rebase_force_push_is_judged_on_the_new_head(self):
        self._assert_judged_on_new_head([_conflicted_then_rebased, _rebase_clears_conflict])

    def test_a_rework_push_is_judged_on_the_new_head(self):
        self._assert_judged_on_new_head([_rework_push])


def _concluded(github, clock):
    github._check_runs_by_sha[(_PR, "sha1")] = (CheckRun("ci", "completed", "success"),)
    github.touch(_PR, 1000.0 + clock[0])
    return clock[0]


def _run_until_done(store, step, run, clock, concluded_at):
    while clock[0] <= concluded_at + 4 * _POLL:
        run(_TICK)
        if store.get_node(step).state.value == "done":
            return clock[0] - _TICK
    raise AssertionError("poll-ci was never judged")


class TestCiJudgementWaitsForAConfirmingPoll(unittest.TestCase):
    def test_a_step_created_between_a_push_and_the_next_poll_does_not_judge_the_old_head(self):
        github, store, item, snapshot, run, clock = _head_change_pool([_rework_push], settle=False)
        second = store.create_step(step="poll-ci", role="engine", parent=item)
        run(3 * _TICK)
        self.assertEqual(store.get_node(second).state.value, "queued")
        self.assertEqual([a for a in store.item_artifacts(second) if a.type == "ci-judged-sha"], [])

        concluded_at = _concluded(github, clock)
        judged_at = _run_until_done(store, second, run, clock, concluded_at)

        self.assertLessEqual(judged_at - concluded_at, _POLL + _TICK)
        judged = [a.value for a in store.item_artifacts(second) if a.type == "ci-judged-sha"]
        self.assertEqual(judged, ["sha1"])
        self.assertIn("sha1", store.get_node(second).report)
        self.assertIn((_PR, "sha0"), github._check_runs_by_sha)

    def test_a_step_first_seen_on_a_poll_tick_is_judged_on_the_following_tick(self):
        github, store, item, snapshot, run, clock = _head_change_pool([_rework_push], settle=False)
        concluded_at = _concluded(github, clock)
        while clock[0] % _POLL != 0:
            run(_TICK)
        second = store.create_step(step="poll-ci", role="engine", parent=item)

        run(_TICK)
        self.assertEqual(store.get_node(second).state.value, "queued")
        run(_TICK)

        self.assertEqual(store.get_node(second).state.value, "done")
        self.assertLessEqual(clock[0] - _TICK - concluded_at, _POLL + _TICK)
        judged = [a.value for a in store.item_artifacts(second) if a.type == "ci-judged-sha"]
        self.assertEqual(judged, ["sha1"])


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
        self.assertEqual(github.calls, [("rate_limit",)])

        watching.append(_PR)
        tick.execute(TickInput(now=2.0 * _TICK))
        self.assertEqual(runner.starts, 2)


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


def _conflict_after_unsettled_read(github):
    github._conflicted.add(_PR)
    github.leave_unsettled(_PR)
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


def _noticed_after(event, seen, polls=40):
    github = FakeGitHub(
        updated_ats={_PR: 100.0, _OTHER: 100.0}, head_shas={_PR: "h0", _OTHER: "h0"})
    snapshot = PrSnapshot(github)
    monitor = _ProbeMonitor(snapshot, seen)
    tick = _tick(monitor, _gate(snapshot, github, InlineGithubPollRunner()))

    happened_at = 7.0
    noticed_at = None
    fired = False
    for n in range(0, polls):
        now = float(n * _TICK)
        if not fired and now >= happened_at:
            event(github)
            fired = True
        snapshot.pr_sync_state(_OTHER)
        tick.execute(TickInput(now=now))
        if fired and monitor.reads[-1] is True and noticed_at is None:
            noticed_at = now
    return None if noticed_at is None else noticed_at - happened_at


class TestLatency(unittest.TestCase):
    def test_each_event_on_a_watched_pr_is_seen_within_one_poll_interval_plus_a_tick(self):
        for name, (event, seen) in _EVENTS.items():
            with self.subTest(event=name):
                latency = _noticed_after(event, seen)

                self.assertIsNotNone(latency)
                self.assertLessEqual(latency, _POLL + _TICK)

    def test_conflict_after_unsettled_first_read_is_seen_within_two_polls_plus_a_tick(self):
        latency = _noticed_after(
            _conflict_after_unsettled_read, lambda s: _flag(s.pr_sync_state(_PR), "conflicted"))

        self.assertIsNotNone(latency)
        self.assertLessEqual(latency, 2 * _POLL + _TICK)


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


class _Rig:
    def __init__(self, runner):
        self.url = "https://github.com/acme/widget/pull/9"
        self.github = FakeGitHub(
            behind_prs={self.url}, head_shas={self.url: "h1"}, strict_bases={_BASE},
            updated_ats={self.url: 1.0})
        self.snapshot = PrSnapshot(self.github)
        self.writes = PrWrites(time.monotonic)
        self.store = FakeStore()
        item = self.store.create_item("feature", "d")
        plant_pr(self.store, item, self.url)
        self.step = self.store.create_step(step="watch-step", role="human", parent=item)
        flow = _FlowAdapter(_BEHIND_FLOW)
        self.monitor = MonitorPrsUseCase(
            self.store, self.snapshot, FakeWorktrees(), flow, CompleteStepUseCase(self.store, flow),
            trusted_authors=lambda: frozenset({"reviewer"}), held_shortcode=lambda: "HLD",
            writes=self.writes, ci_clock=time.monotonic, ci_poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, ci_wall_clock=lambda: 10000.0, ci_views=self.snapshot)
        self.poll = GithubPollUseCase(self.snapshot, self.github, runner, _Config(), self.writes, FakeGithubBudgetStatus(), time.time, FakeFs())

    def notes(self):
        return self.store.get_node(self.step).notes or ""


class TestWritesStayOffTheTick(unittest.TestCase):
    def test_a_poll_that_never_returns_leaves_both_port_calls_unmade(self):
        runner = BlockingGithubPollRunner()
        rig = _Rig(runner)

        for n in range(30):
            rig.monitor.execute()
            rig.poll.execute(float(n * _TICK))

        self.assertEqual((rig.github.update_calls, rig.github.requires_calls), ([], []))
        runner.pending[0]()
        self.assertEqual(rig.github.calls.count(("pr_view", rig.url)), 1)
        self.assertEqual(rig.github.update_calls, [])
        self.assertEqual(rig.github.requires_calls, [])

    def test_the_decided_update_lands_within_one_poll_interval_plus_one_tick(self):
        rig = _Rig(InlineGithubPollRunner())
        performed_at = None
        applied_at = None

        for n in range(_POLL // _TICK + 3):
            now = float(n * _TICK)
            response = rig.monitor.execute()
            if response.updated and applied_at is None:
                applied_at = now
            rig.poll.execute(now)
            if rig.github.update_calls and performed_at is None:
                performed_at = now

        self.assertEqual(performed_at, float(_POLL))
        self.assertEqual(applied_at, float(_POLL + _TICK))
        self.assertLessEqual(applied_at, _POLL + _TICK)
        self.assertEqual(rig.github.update_calls, [(rig.url, "h1")])
        self.assertIn("Branch updated onto main", rig.notes())
