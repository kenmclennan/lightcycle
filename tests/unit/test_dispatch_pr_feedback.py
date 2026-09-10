import unittest

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.pool.check_content_pin import CheckContentPinUseCase
from lightcycle.application.pool.dispatch_pr_feedback import DispatchPrFeedbackUseCase
from lightcycle.application.pool.resolve_merged_prs import ResolveMergedPrsUseCase
from lightcycle.domain.feedback import LC_MARKER
from lightcycle.domain.work import State
from lightcycle.ports.github import Comment, Review
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore

_BOT_LOGIN = "copilot-pull-request-reviewer[bot]"


def plant_pr(store, item, url, phase=None, branch=None, n=1, state="open"):
    while store.current_pass(item) is None or store.current_pass(item).n < n:
        current = store.current_pass(item)
        if current is not None:
            store.close_pass(current.id)
        store.open_pass(item)
    rid = store.open_run(item, store.current_pass(item).id, phase)
    store.set_branch(rid, branch)
    store.set_pr(rid, url)
    if state != "open":
        store.close_run(rid, state)
    return rid


class _FlowAdapter:
    def __init__(self, flow):
        self._flow = flow

    def workflow_for(self, step):
        return "wf"

    def project_for(self, step):
        return None

    def load_flow(self, name=None, project=None):
        return self._flow

    def flow_for(self, node):
        return self._flow

    def flow_next(self, step, outcome, name=None, project=None):
        return self._flow.next(step, outcome)

    def outcomes_for(self, step, name=None, project=None):
        return self._flow.outcomes_for(step)

    def meta_for_step(self, step, name=None, project=None):
        return {}

    def owner_of(self, step, name=None, project=None):
        return self._flow.owner_of(step)

    def ci_failed_cap_outcome(self, step, name=None, project=None):
        return self._flow.ci_failed_cap_outcome(step)

    def ci_failed_cap_n(self, step, name=None, project=None):
        return self._flow.ci_failed_cap_n(step)

    def ci_failed_cap_target(self, step, name=None, project=None):
        return self._flow.ci_failed_cap_target(step)

    def effective_transition(self, transition, outcome, prior_count, name=None, project=None):
        return self._flow.effective_transition(transition, outcome, prior_count)

    def phase_for(self, node):
        return self._flow.phase_of(getattr(node, "step", None))

    def phase_for_stage(self, stage, name=None):
        return "code"

    def ends_pass(self, stage, outcome, name=None):
        return False


_FLOW = flow_from_metas(
    {
        "reviewer": {
            "step": "ready-merge",
            "routes": {"merged": "cleanup", "changes": "build"},
            "on_pr_merge": "merged",
            "on_pr_close": "abandoned",
        }
    },
    disposition={"merged": "completed", "abandoned": "aborted"},
)

_FEEDBACK_FLOW = flow_from_metas(
    {
        "handle-feedback": {
            "model": "sonnet",
            "step": "handle-feedback",
        },
        "reviewer": {
            "step": "ready-merge",
            "routes": {"changes": "build"},
            "on_pr_feedback": "handle-feedback",
            "on_mention_token": "@lc",
            "on_review_bot_allowlist": [_BOT_LOGIN],
        },
    }
)

_NO_MENTION_TOKEN_FLOW = flow_from_metas(
    {
        "handle-feedback": {
            "model": "sonnet",
            "step": "handle-feedback",
        },
        "reviewer": {
            "step": "ready-merge",
            "routes": {"changes": "build"},
            "on_pr_feedback": "handle-feedback",
        },
    }
)

_CONFLICT_FLOW = flow_from_metas({
    "watcher": {
        "model": "sonnet",
        "step": "watch-step",
        "routes": {"conflicted": "fix-step", "gave-up": "escalate-step"},
        "on_pr_conflict": "conflicted",
        "on_pr_conflict_cap": 2,
        "on_pr_conflict_escalate": "gave-up",
    },
    "fixer": {
        "model": "sonnet",
        "step": "fix-step",
        "routes": {"resolved": "watch-step"},
    },
})

_READY_MERGE_QUAD_FLOW = flow_from_metas({
    "handle-feedback": {
        "model": "sonnet",
        "step": "handle-feedback",
    },
    "reviewer": {
        "model": "sonnet",
        "step": "watch-pr",
        "routes": {
            "merged": "done-step",
            "abandoned": "done-step",
            "changes": "build-step",
            "conflicted": "resolve-step",
        },
        "on_pr_merge": "merged",
        "on_pr_close": "abandoned",
        "on_pr_feedback": "handle-feedback",
        "on_pr_conflict": "conflicted",
        "on_mention_token": "@lc",
        "on_review_bot_allowlist": [_BOT_LOGIN],
    },
    "resolver": {
        "model": "sonnet",
        "step": "resolve-step",
        "routes": {"resolved": "watch-pr", "escalate": "human-step"},
    },
})


class FakeWorktrees:
    def release_run(self, run, delete_remote=True):
        self.released = getattr(self, "released", [])
        self.released.append(run.id)

    def __init__(self):
        self.removed = []

    def remove(self, item):
        self.removed.append(item)


class TestMonitorPrsFeedback(unittest.TestCase):
    def _setup(self, pr_url, github, flow=None):
        f = flow or _FEEDBACK_FLOW
        store = FakeStore()
        item = store.create_item("in-review feature", "a description")
        plant_pr(store, item, pr_url)
        step = store.create_step(
            "ready-merge: in-review feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        uc = DispatchPrFeedbackUseCase(store, github, _FlowAdapter(f), None)
        return store, item, step, worktrees, uc

    def _spawned_feedback_steps(self, store, watched_step):
        return [
            t for t in store.all_nodes()
            if t.id != watched_step and t.type == "step" and t.step == "handle-feedback"
        ]

    def _mention_comment(self, ts, body="@lc fix the tests", author="reviewer", cid=None):
        return (
            ts,
            Comment(author=author, body=body, is_top_level=True,
                    id=cid or str(ts), created_at=ts),
        )

    def _inline_comment(self, ts, body="nit: rename this", author="reviewer",
                         cid=None, in_reply_to=None):
        return (
            ts,
            Comment(
                author=author,
                body=body,
                is_top_level=False,
                path="src/foo.py",
                line=42,
                id=cid or str(ts),
                in_reply_to_id=in_reply_to,
                created_at=ts,
            ),
        )

    def _bot_review(self, ts, author=_BOT_LOGIN, body="looks like a bug on line 12", state="COMMENTED"):
        return (ts, Review(author=author, body=body, created_at=ts, state=state))

    def test_mention_comment_after_push_spawns_handle_feedback(self):
        url = "https://github.com/x/y/pull/30"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])
        spawned = self._spawned_feedback_steps(store, step)
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0].role, "agent")
        self.assertEqual(spawned[0].parent, item)
        self.assertEqual(spawned[0].state, State.QUEUED)
        self.assertNotEqual(store.get_node(step).state, "done")
        self.assertEqual(store.get_step(spawned[0].id).watched_step, step)
        run = store.current_run(item, None)
        self.assertEqual(run.comments_dispatched_through, "1500.0")

    def test_inline_comment_without_mention_token_still_spawns(self):
        url = "https://github.com/x/y/pull/30-inline"
        gh = FakeGitHub(
            push_time=1000.0,
            timed_comments=[self._inline_comment(1500.0, body="please rename this")],
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])

    def test_threaded_comment_with_lc_reply_does_not_spawn(self):
        url = "https://github.com/x/y/pull/30-threaded"
        root = self._inline_comment(1200.0, cid="c1")
        reply = self._inline_comment(
            1300.0, body="answered %s" % LC_MARKER, cid="c2", in_reply_to="c1"
        )
        gh = FakeGitHub(push_time=1000.0, timed_comments=[root, reply])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_threaded_comment_with_later_unmarked_reply_records_reply_timestamp(self):
        url = "https://github.com/x/y/pull/30-threaded-live-reply"
        root = self._inline_comment(1200.0, body="please fix X", cid="c1")
        reply = self._inline_comment(
            1300.0, body="actually scratch that", cid="c2", in_reply_to="c1"
        )
        gh = FakeGitHub(push_time=1000.0, timed_comments=[root, reply])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])
        run = store.current_run(item, None)
        self.assertEqual(run.comments_dispatched_through, str(1300.0))

    def test_allowlisted_bot_review_spawns(self):
        url = "https://github.com/x/y/pull/30-bot"
        gh = FakeGitHub(push_time=1000.0, timed_reviews=[self._bot_review(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])

    def test_non_allowlisted_bot_review_does_not_trigger(self):
        url = "https://github.com/x/y/pull/30-other-bot"
        gh = FakeGitHub(
            push_time=1000.0,
            timed_reviews=[self._bot_review(1500.0, author="some-other[bot]")],
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertNotEqual(store.get_node(step).state, "done")

    def test_plain_comment_without_mention_token_does_not_trigger(self):
        url = "https://github.com/x/y/pull/34"
        gh = FakeGitHub(
            push_time=1000.0,
            timed_comments=[self._mention_comment(1500.0, body="just a plain comment")],
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertNotEqual(store.get_node(step).state, "done")
        self.assertEqual(worktrees.removed, [])

    def test_mention_comment_before_push_does_not_fire(self):
        url = "https://github.com/x/y/pull/35"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_bot_comment_with_mention_token_does_not_trigger(self):
        url = "https://github.com/x/y/pull/36"
        bot_comment = self._mention_comment(1500.0, body="@lc", author="some-ci[bot]")
        gh = FakeGitHub(push_time=1000.0, timed_comments=[bot_comment])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_lc_marked_comment_does_not_trigger(self):
        url = "https://github.com/x/y/pull/37"
        marked = self._mention_comment(
            1200.0, body="@lc already handled this %s" % LC_MARKER, author="lc"
        )
        gh = FakeGitHub(push_time=1000.0, timed_comments=[marked])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_lc_marked_review_does_not_trigger(self):
        url = "https://github.com/x/y/pull/37-review"
        marked = (
            1200.0,
            Review(
                author=_BOT_LOGIN,
                body="already replied %s" % LC_MARKER,
                created_at=1200.0,
                state="COMMENTED",
            ),
        )
        gh = FakeGitHub(push_time=1000.0, timed_reviews=[marked])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_marked_reply_after_review_clears_it(self):
        url = "https://github.com/x/y/pull/37-review-replied"
        review = self._bot_review(1200.0)
        reply = self._mention_comment(
            1300.0, body="handled, ignoring %s" % LC_MARKER, author="lc"
        )
        gh = FakeGitHub(push_time=1000.0, timed_reviews=[review], timed_comments=[reply])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_approved_review_with_body_does_not_trigger(self):
        url = "https://github.com/x/y/pull/37-approved"
        gh = FakeGitHub(
            push_time=1000.0,
            timed_reviews=[self._bot_review(1500.0, body="thanks, nice work", state="APPROVED")],
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_commented_review_with_empty_body_does_not_trigger(self):
        url = "https://github.com/x/y/pull/37-commented-empty"
        gh = FakeGitHub(
            push_time=1000.0,
            timed_reviews=[self._bot_review(1500.0, body="", state="COMMENTED")],
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_changes_requested_review_with_empty_body_still_triggers(self):
        url = "https://github.com/x/y/pull/37-changes-requested-empty"
        gh = FakeGitHub(
            push_time=1000.0,
            timed_reviews=[self._bot_review(1500.0, body="", state="CHANGES_REQUESTED")],
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])

    def test_commented_review_with_body_triggers(self):
        url = "https://github.com/x/y/pull/37-commented-with-body"
        gh = FakeGitHub(push_time=1000.0, timed_reviews=[self._bot_review(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])

    def test_no_mention_token_configured_never_fires_on_top_level(self):
        url = "https://github.com/x/y/pull/37-no-config"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh, flow=_NO_MENTION_TOKEN_FLOW)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_no_double_spawn_when_one_already_open(self):
        url = "https://github.com/x/y/pull/40"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        uc.execute()
        uc.execute()

        self.assertEqual(len(self._spawned_feedback_steps(store, step)), 1)

    def test_watermark_advance_stops_the_same_mention_from_refiring(self):
        url = "https://github.com/x/y/pull/41"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        uc.execute()
        spawned = self._spawned_feedback_steps(store, step)
        store.complete_node(spawned[0].id, "done")
        store.replace_artifact(step, "feedback-watermark", "1500.0")

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_closed_without_watermark_advance_does_not_duplicate_spawn(self):
        url = "https://github.com/x/y/pull/41-closed-early"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        uc.execute()
        spawned = self._spawned_feedback_steps(store, step)
        store.complete_node(spawned[0].id, "done")

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertEqual(len(self._spawned_feedback_steps(store, step)), 0)

    def test_multi_round_new_comments_are_outstanding_independent_of_timestamp(self):
        url = "https://github.com/x/y/pull/42"
        round1 = self._inline_comment(1200.0, cid="c1")
        gh = FakeGitHub(push_time=1000.0, timed_comments=[round1])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result1 = uc.execute()
        self.assertEqual(result1.reworked, [item])
        spawned1 = self._spawned_feedback_steps(store, step)
        self.assertEqual(len(spawned1), 1)

        reply1 = self._inline_comment(
            1250.0, body="queued %s" % LC_MARKER, cid="c1-reply", in_reply_to="c1"
        )
        store.complete_node(spawned1[0].id, "done")
        gh._timed_comments = [round1, reply1]

        result2 = uc.execute()
        self.assertEqual(result2.reworked, [])

        round2 = self._inline_comment(1400.0, cid="c2", body="another nit")
        gh._timed_comments = [round1, reply1, round2]

        result3 = uc.execute()
        self.assertEqual(result3.reworked, [item])
        spawned3 = self._spawned_feedback_steps(store, step)
        self.assertEqual(len(spawned3), 1)

    def test_last_push_time_failure_declines_to_conclude_feedback(self):
        url = "https://github.com/x/y/pull/50"
        gh = FakeGitHub(
            push_time=1000.0, timed_comments=[self._mention_comment(1500.0)],
            failing_calls={"last_push_time"},
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertEqual(self._spawned_feedback_steps(store, step), [])
        notes = store.get_node(step).notes
        self.assertIn("gh read failed", notes)
        self.assertIn("boom", notes)

    def test_last_push_time_failure_does_not_grow_the_note_across_polls(self):
        url = "https://github.com/x/y/pull/50-repeat"
        gh = FakeGitHub(
            push_time=1000.0, timed_comments=[self._mention_comment(1500.0)],
            failing_calls={"last_push_time"},
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        uc.execute()
        first = store.get_node(step).notes
        uc.execute()
        second = store.get_node(step).notes

        self.assertEqual(len(first.splitlines()), 1)
        self.assertEqual(len(second.splitlines()), 1)
        self.assertIn("gh read failed", second)
        self.assertIn("boom", second)
        self.assertIn("x2", second)

        uc.execute()
        third = store.get_node(step).notes
        self.assertEqual(len(third.splitlines()), 1)
        self.assertIn("x3", third)

    def test_comments_since_failure_declines_to_conclude_feedback(self):
        url = "https://github.com/x/y/pull/51"
        gh = FakeGitHub(
            push_time=1000.0, timed_comments=[self._mention_comment(1500.0)],
            failing_calls={"comments_since"},
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertEqual(self._spawned_feedback_steps(store, step), [])
        notes = store.get_node(step).notes
        self.assertIn("gh read failed", notes)
        self.assertIn("boom", notes)

    def test_pull_comments_failure_declines_to_conclude_feedback(self):
        url = "https://github.com/x/y/pull/52"
        gh = FakeGitHub(
            push_time=1000.0, timed_comments=[self._inline_comment(1500.0)],
            failing_calls={"pull_comments"},
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertEqual(self._spawned_feedback_steps(store, step), [])
        notes = store.get_node(step).notes
        self.assertIn("gh read failed", notes)
        self.assertIn("boom", notes)

    def test_reviews_failure_declines_to_conclude_feedback(self):
        url = "https://github.com/x/y/pull/53"
        gh = FakeGitHub(
            push_time=1000.0, timed_reviews=[self._bot_review(1500.0)],
            failing_calls={"reviews"},
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertEqual(self._spawned_feedback_steps(store, step), [])
        notes = store.get_node(step).notes
        self.assertIn("gh read failed", notes)
        self.assertIn("boom", notes)

    def test_merged_pr_takes_merge_path_not_feedback(self):
        url = "https://github.com/x/y/pull/39"
        gh = FakeGitHub(
            merged_prs={url}, push_time=1000.0, timed_comments=[self._mention_comment(1500.0)]
        )
        store = FakeStore()
        item = store.create_item("in-review feature", "a description")
        plant_pr(store, item, url)
        store.create_step(
            "ready-merge: in-review feature", step="ready-merge", role="human", parent=item
        )
        check_content_pin = CheckContentPinUseCase(store, gh)
        resolve = ResolveMergedPrsUseCase(
            store, gh, FakeWorktrees(), _FlowAdapter(_FLOW), None, check_content_pin
        )
        dispatch = DispatchPrFeedbackUseCase(store, gh, _FlowAdapter(_FLOW), None)

        resolved = resolve.execute()
        dispatched = dispatch.execute()

        self.assertEqual(resolved.merged, [item])
        self.assertEqual(dispatched.reworked, [])
        self.assertEqual(store.get_node(item).state, "done")




class TestMonitorPrsConflict(unittest.TestCase):

    def _setup(self, pr_url, github, flow=None, prior_conflicts=0):
        f = flow or _CONFLICT_FLOW
        store = FakeStore()
        item = store.create_item("conflicting feature", "a description")
        plant_pr(store, item, pr_url)
        for _ in range(prior_conflicts):
            old = store.create_step("watch-step: conflicting feature", step="watch-step",
                                    role="agent", parent=item)
            store.complete_node(old, "conflicted")
        step = store.create_step("watch-step: conflicting feature", step="watch-step",
                                 role="agent", parent=item)
        worktrees = FakeWorktrees()
        complete = CompleteStepUseCase(store, _FlowAdapter(f))
        uc = DispatchPrFeedbackUseCase(store, github, _FlowAdapter(f), complete)
        return store, item, step, worktrees, uc

    def test_conflicting_pr_advances_task_via_conflict_outcome(self):
        url = "https://github.com/x/y/pull/50"
        store, item, step, _, uc = self._setup(url, FakeGitHub(conflicted_prs={url}))

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).state, "done")
        self.assertEqual(store.get_node(step).outcome, "conflicted")

    def test_conflicting_pr_creates_fix_task(self):
        url = "https://github.com/x/y/pull/51"
        store, item, step, _, uc = self._setup(url, FakeGitHub(conflicted_prs={url}))

        uc.execute()

        steps = [t for t in store.all_nodes() if t.id != step and t.type == "step"
                 and t.state != "done"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].step, "fix-step")

    def test_unknown_mergeable_state_does_not_trigger_conflict(self):
        url = "https://github.com/x/y/pull/52"
        store, item, step, _, uc = self._setup(url, FakeGitHub())

        result = uc.execute()

        self.assertEqual(result.conflicted, [])
        self.assertNotEqual(store.get_node(step).state, "done")

    def test_is_conflicted_failure_does_not_route_to_rework(self):
        url = "https://github.com/x/y/pull/54"
        store, item, step, _, uc = self._setup(
            url, FakeGitHub(conflicted_prs={url}, failing_calls={"is_conflicted"})
        )

        result = uc.execute()

        self.assertEqual(result.conflicted, [])
        self.assertNotEqual(store.get_node(step).state, "done")

    def test_merged_pr_does_not_take_conflict_path(self):
        url = "https://github.com/x/y/pull/53"
        flow = flow_from_metas({
            "watcher": {
                "model": "sonnet",
                "step": "watch-step",
                "routes": {"merged": "done-step", "conflicted": "fix-step"},
                "on_pr_merge": "merged",
                "on_pr_conflict": "conflicted",
            },
        }, disposition={"merged": "completed"})
        store = FakeStore()
        item = store.create_item("conflicting feature", "a description")
        plant_pr(store, item, url)
        store.create_step("watch-step: conflicting feature", step="watch-step",
                           role="agent", parent=item)
        gh = FakeGitHub(merged_prs={url}, conflicted_prs={url})
        complete = CompleteStepUseCase(store, _FlowAdapter(flow))
        check_content_pin = CheckContentPinUseCase(store, gh)
        resolve = ResolveMergedPrsUseCase(
            store, gh, FakeWorktrees(), _FlowAdapter(flow), complete, check_content_pin
        )
        dispatch = DispatchPrFeedbackUseCase(store, gh, _FlowAdapter(flow), complete)

        resolved = resolve.execute()
        dispatched = dispatch.execute()

        self.assertEqual(resolved.merged, [item])
        self.assertEqual(dispatched.conflicted, [])

    def test_arbitrary_step_names_work_for_conflict(self):
        url = "https://github.com/x/y/pull/54"
        arbitrary_flow = flow_from_metas({
            "sentinel": {
                "model": "claude",
                "step": "await-green",
                "routes": {"stuck": "untangle-step"},
                "on_pr_conflict": "stuck",
            }
        })
        store = FakeStore()
        item = store.create_item("arbitrary", "a description")
        plant_pr(store, item, url)
        step = store.create_step("await-green: arbitrary", step="await-green",
                                 role="agent", parent=item)
        complete = CompleteStepUseCase(store, _FlowAdapter(arbitrary_flow))
        uc = DispatchPrFeedbackUseCase(store, FakeGitHub(conflicted_prs={url}), _FlowAdapter(arbitrary_flow), complete)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).outcome, "stuck")

    def test_escalates_after_cap_reached(self):
        url = "https://github.com/x/y/pull/55"
        store, item, step, _, uc = self._setup(
            url, FakeGitHub(conflicted_prs={url}), prior_conflicts=2)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).outcome, "gave-up")

    def test_under_cap_uses_conflict_outcome(self):
        url = "https://github.com/x/y/pull/56"
        store, item, step, _, uc = self._setup(
            url, FakeGitHub(conflicted_prs={url}), prior_conflicts=1)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).outcome, "conflicted")

    def test_escalated_task_surfaces_for_human(self):
        url = "https://github.com/x/y/pull/57"
        store, item, step, _, uc = self._setup(
            url, FakeGitHub(conflicted_prs={url}), prior_conflicts=2)

        uc.execute()

        steps = [t for t in store.all_nodes() if t.id != step and t.type == "step"
                 and t.state != "done"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].role, "human")
        self.assertEqual(steps[0].step, "escalate-step")

    def test_conflict_fires_when_step_also_declares_feedback(self):
        url = "https://github.com/x/y/pull/59"
        store = FakeStore()
        item = store.create_item("quad feature", "a description")
        plant_pr(store, item, url)
        step = store.create_step("watch-pr: quad feature", step="watch-pr", role="agent",
                                 parent=item)
        complete = CompleteStepUseCase(store, _FlowAdapter(_READY_MERGE_QUAD_FLOW))
        uc = DispatchPrFeedbackUseCase(store, FakeGitHub(conflicted_prs={url}), _FlowAdapter(_READY_MERGE_QUAD_FLOW), complete)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(result.reworked, [])
        self.assertEqual(store.get_node(step).outcome, "conflicted")

    def test_feedback_wins_over_conflict_when_both_conditions_true(self):
        url = "https://github.com/x/y/pull/60"
        store = FakeStore()
        item = store.create_item("both quad feature", "a description")
        plant_pr(store, item, url)
        step = store.create_step("watch-pr: both quad feature", step="watch-pr", role="agent",
                                 parent=item)
        feedback_comment = (
            1500.0,
            Comment(author="reviewer", body="@lc fix it", is_top_level=True,
                    id="c1", created_at=1500.0),
        )
        gh = FakeGitHub(conflicted_prs={url}, push_time=1000.0, timed_comments=[feedback_comment])
        complete = CompleteStepUseCase(store, _FlowAdapter(_READY_MERGE_QUAD_FLOW))
        uc = DispatchPrFeedbackUseCase(store, gh, _FlowAdapter(_READY_MERGE_QUAD_FLOW), complete)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])
        self.assertEqual(result.conflicted, [])
        self.assertNotEqual(store.get_node(step).state, "done")
        spawned = [
            t for t in store.all_nodes()
            if t.id != step and t.type == "step" and t.step == "handle-feedback"
        ]
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0].parent, item)

    def test_no_cap_declared_never_escalates(self):
        url = "https://github.com/x/y/pull/58"
        no_cap_flow = flow_from_metas({
            "watcher": {
                "model": "sonnet",
                "step": "watch-step",
                "routes": {"conflicted": "fix-step"},
                "on_pr_conflict": "conflicted",
            },
            "fixer": {
                "model": "sonnet",
                "step": "fix-step",
                "routes": {"resolved": "watch-step"},
            },
        })
        store = FakeStore()
        item = store.create_item("no-cap feature", "a description")
        plant_pr(store, item, url)
        for _ in range(5):
            old = store.create_step("watch-step: no-cap feature", step="watch-step",
                                    role="agent", parent=item)
            store.complete_node(old, "conflicted")
        step = store.create_step("watch-step: no-cap feature", step="watch-step",
                                 role="agent", parent=item)
        complete = CompleteStepUseCase(store, _FlowAdapter(no_cap_flow))
        uc = DispatchPrFeedbackUseCase(store, FakeGitHub(conflicted_prs={url}), _FlowAdapter(no_cap_flow), complete)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).outcome, "conflicted")




