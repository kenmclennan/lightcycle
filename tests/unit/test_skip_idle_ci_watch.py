import time
import unittest

from lightcycle.application.flow.complete_step import CompleteStepUseCase
from lightcycle.application.pool.resolve_ci import ResolveCiUseCase
from lightcycle.config import ConfigError
from lightcycle.domain.feedback import LC_MARKER
from lightcycle.domain.work import State
from lightcycle.ports.github import CheckRun, Comment, NotYetRead, Review
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.fake_view_freshness import AlwaysConfirmed, NeverConfirmed
from tests.unit.test_resolve_ci import _BRANCH, _URL, _FlowAdapter, plant_pr

_PUSH = 100.0
_PASSING = {(_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="success"),)}
_FAILING = {(_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="failure"),)}
_HUNG = {(_URL, "sha1"): (CheckRun(name="build", status="in_progress", conclusion=None, started_at=1.0),)}


def _flow(always_run=False):
    watcher = {"model": "sonnet", "step": "watch-ci", "routes": {"done": "review"}}
    if always_run:
        watcher["always-run"] = True
    return flow_from_metas({
        "poller": {
            "engine": True, "step": "poll-ci",
            "routes": {"succeeded": "watch-ci", "failed": "watch-ci"},
            "on_ci_success": "succeeded", "on_ci_failure": "failed",
        },
        "watcher": watcher,
        "reviewer": {"model": "sonnet", "step": "review"},
    })


def _trusted():
    return frozenset({"alice"})


def _comment(author="alice", body="please fix", top_level=True, **kw):
    return Comment(author=author, body=body, is_top_level=top_level, id=kw.pop("id", "c1"), **kw)


def _gh(checks=None, comments=(), reviews=(), **kw):
    return FakeGitHub(
        head_shas={_URL: "sha1"}, check_runs_by_sha=_PASSING if checks is None else checks,
        push_time=_PUSH, timed_comments=list(comments), timed_reviews=list(reviews), **kw)


class _Rig:
    def __init__(self, github, flow=None, views=None, trusted=_trusted, wrap=None):
        self.store = FakeStore()
        self.item = self.store.create_item("building a thing", "a description")
        plant_pr(self.store, self.item, _URL, branch=_BRANCH)
        self.poll = self.store.create_step(stage="poll-ci", role="engine", item=self.item)
        adapter = _FlowAdapter(flow or _flow())
        complete = CompleteStepUseCase(self.store, adapter)
        if wrap:
            complete = wrap(self.store, complete)
        self.uc = ResolveCiUseCase(
            self.store, github, adapter, complete, clock=time.monotonic, poll_seconds=lambda: 60,
            ci_ceiling_seconds=lambda: 3600, wall_clock=lambda: 10000.0,
            views=views or AlwaysConfirmed(), trusted_authors=trusted)

    def step(self, stage):
        found = [c for c in self.store.children(self.item) if c.stage == stage]
        return found[0] if found else None


class TestGreenAndIdle(unittest.TestCase):
    def test_closes_the_watcher_done_without_a_claim_and_names_the_skip(self):
        rig = _Rig(_gh())

        result = rig.uc.execute()

        watch = rig.step("watch-ci")
        self.assertEqual(watch.state, State.DONE)
        self.assertEqual(watch.outcome, "done")
        self.assertIsNone(watch.claimed_by)
        self.assertIn("Skipped by the engine", watch.report)
        self.assertIn("sha1", watch.report)
        self.assertEqual(rig.step("review").state, State.QUEUED)
        self.assertEqual(result.ci_resolved, [rig.item])


class TestFeedbackKeepsTheAgent(unittest.TestCase):
    def _kept(self, github):
        rig = _Rig(github)
        rig.uc.execute()
        self.assertEqual(rig.step("watch-ci").state, State.QUEUED)
        self.assertIsNone(rig.step("review"))

    def test_trusted_top_level_comment(self):
        self._kept(_gh(comments=[(_PUSH + 1, _comment())]))

    def test_trusted_inline_comment(self):
        self._kept(_gh(comments=[(_PUSH + 1, _comment(top_level=False, path="a.py", line=1))]))

    def test_trusted_review_requesting_changes(self):
        self._kept(_gh(reviews=[(_PUSH + 1, Review(author="alice", body="", state="CHANGES_REQUESTED", id="r1"))]))

    def test_trusted_commented_review_with_a_body(self):
        self._kept(_gh(reviews=[(_PUSH + 1, Review(author="alice", body="hm", state="COMMENTED", id="r1"))]))


class TestFeedbackThatDoesNotBlock(unittest.TestCase):
    def _skipped(self, github):
        rig = _Rig(github)
        rig.uc.execute()
        self.assertEqual(rig.step("watch-ci").state, State.DONE)

    def test_comment_dated_at_the_cutoff(self):
        self._skipped(_gh(comments=[(_PUSH, _comment())]))

    def test_comment_a_fraction_above_the_cutoff_blocks(self):
        rig = _Rig(_gh(comments=[(_PUSH + 0.001, _comment())]))
        rig.uc.execute()
        self.assertEqual(rig.step("watch-ci").state, State.QUEUED)

    def test_untrusted_comment(self):
        self._skipped(_gh(comments=[(_PUSH + 1, _comment(author="mallory"))]))

    def test_engine_marked_comment(self):
        self._skipped(_gh(comments=[(_PUSH + 1, _comment(body="done %s" % LC_MARKER))]))

    def test_approved_held_comment_blocks(self):
        rig = _Rig(_gh())
        run = rig.store.current_run(rig.item, None)
        rig.store.file_hold(run.id, "k1", "mallory", "body", None, None, 1.0)
        hold_step = rig.store.create_step(stage="held-comment", role="human", item=rig.item)
        rig.store.attach_hold(run.id, "k1", rig.item, hold_step)
        rig.store.decide_hold(hold_step, "approved")
        rig.uc.execute()
        self.assertEqual(rig.step("watch-ci").state, State.QUEUED)


class TestNonGreenKeepsTheAgent(unittest.TestCase):
    def test_failed_ci(self):
        rig = _Rig(_gh(checks=_FAILING))
        rig.uc.execute()
        self.assertEqual(rig.step("watch-ci").state, State.QUEUED)

    def test_timed_out_ci(self):
        rig = _Rig(_gh(checks=_HUNG))
        rig.uc.execute()
        self.assertEqual(rig.step("watch-ci").state, State.QUEUED)


class TestUnconfirmedReads(unittest.TestCase):
    def test_unconfirmed_view_completes_nothing(self):
        rig = _Rig(_gh(), views=NeverConfirmed())
        rig.uc.execute()
        self.assertEqual(rig.store.get_node(rig.poll).state, State.QUEUED)
        self.assertIsNone(rig.step("watch-ci"))

    def test_failed_feedback_read_keeps_the_agent(self):
        rig = _Rig(_gh(failing_calls={"comments_since"}))
        rig.uc.execute()
        self.assertEqual(rig.store.get_node(rig.poll).outcome, "succeeded")
        self.assertEqual(rig.step("watch-ci").state, State.QUEUED)

    def test_not_yet_read_push_time_keeps_the_agent(self):
        class _Unread(FakeGitHub):
            def last_push_time(self, pr):
                return NotYetRead()

        rig = _Rig(_Unread(head_shas={_URL: "sha1"}, check_runs_by_sha=_PASSING))
        rig.uc.execute()
        self.assertEqual(rig.step("watch-ci").state, State.QUEUED)

    def test_missing_trusted_authors_keeps_the_agent(self):
        def _unset():
            raise ConfigError("trusted-authors")

        rig = _Rig(_gh(), trusted=_unset)
        rig.uc.execute()
        self.assertEqual(rig.step("watch-ci").state, State.QUEUED)


class TestMixedPrs(unittest.TestCase):
    def test_each_item_is_judged_on_its_own_feedback(self):
        other = "https://github.com/x/y/pull/91"

        class _PerPr(FakeGitHub):
            def comments_since(self, pr, since):
                return [_comment()] if pr == other else []

        gh = _PerPr(
            head_shas={_URL: "sha1", other: "sha1"},
            check_runs_by_sha={**_PASSING, (other, "sha1"): _PASSING[(_URL, "sha1")]},
            push_time=_PUSH)
        rig = _Rig(gh)
        second = rig.store.create_item("another", "a description")
        plant_pr(rig.store, second, other, branch="feat/other")
        rig.store.create_step(stage="poll-ci", role="engine", item=second)

        result = rig.uc.execute()

        self.assertEqual(sorted(result.ci_resolved), sorted([rig.item, second]))
        self.assertEqual(rig.step("watch-ci").state, State.DONE)
        kept = [c for c in rig.store.children(second) if c.stage == "watch-ci"]
        self.assertEqual(kept[0].state, State.QUEUED)


class TestHeadMoved(unittest.TestCase):
    def test_head_changing_after_the_judgement_keeps_the_agent(self):
        class _Moving(FakeGitHub):
            def __init__(self, **kw):
                super().__init__(**kw)
                self._reads = 0

            def head_sha(self, pr):
                self._reads += 1
                return "sha1" if self._reads <= 1 else "sha2"

        rig = _Rig(_Moving(head_shas={_URL: "sha1"}, check_runs_by_sha=_PASSING, push_time=_PUSH))
        rig.uc.execute()
        self.assertEqual(rig.step("watch-ci").state, State.QUEUED)


class TestAlwaysRun(unittest.TestCase):
    def test_a_stage_declaring_always_run_is_never_skipped(self):
        rig = _Rig(_gh(), flow=_flow(always_run=True))
        rig.uc.execute()
        self.assertEqual(rig.step("watch-ci").state, State.QUEUED)

    def test_step_def_reads_the_key_and_defaults_false(self):
        self.assertTrue(_flow(always_run=True).step_def("watch-ci").always_run)
        self.assertFalse(_flow().step_def("watch-ci").always_run)


class TestClaimedStepIsLeftAlone(unittest.TestCase):
    def test_an_assigned_watcher_is_not_completed(self):
        class _Assigning:
            def __init__(self, store, inner):
                self._store = store
                self._inner = inner

            def execute(self, input):
                done = self._inner.execute(input)
                if done.next_step:
                    self._store.assign(done.next_step, "someone")
                return done

        rig = _Rig(_gh(), wrap=_Assigning)
        rig.uc.execute()
        self.assertNotEqual(rig.step("watch-ci").state, State.DONE)
