import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.dispatch_pr_feedback import DispatchPrFeedbackUseCase
from lightcycle.application.pool.feedback_window import feedback_window_start
from lightcycle.domain.feedback import AUTOMATED_PREFIX, LC_MARKER
from lightcycle.domain.work import State
from lightcycle.ports.github import Comment, NotYetRead, Review
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.null_collaborators import NoopWorktrees
from tests.support.store_seed import held_comment
from tests.unit.test_dispatch_pr_feedback import _FEEDBACK_FLOW, _FlowAdapter, plant_pr

_URL = "https://github.com/acme/widget/pull/7"
_OPERATOR = "kenmclennan"
_BOT = "copilot"
_OUTSIDER = "mallory"


def _inline(ts, author, cid, body="nit: rename this", in_reply_to=None):
    return (ts, Comment(
        author=author, body=body, is_top_level=False, path="a.py", line=3, id=cid,
        in_reply_to_id=in_reply_to, created_at=ts))


def _top(ts, author, cid, body="thanks, looks good"):
    return (ts, Comment(author=author, body=body, is_top_level=True, id=cid, created_at=ts))


def _review(ts, author, rid, body="", state="CHANGES_REQUESTED"):
    return (ts, Review(author=author, body=body, created_at=ts, state=state, id=rid))


class _Rig(unittest.TestCase):
    def _build(self, github, review_bots=(_BOT,), trusted=(_OPERATOR, _BOT)):
        self.github = github
        self.store = FakeStore()
        self.item = self.store.create_item("in-review feature", "a description")
        self.rid = plant_pr(self.store, self.item, _URL)
        self.step = self.store.create_step(stage="ready-merge", role="human", item=self.item)
        adapter = _FlowAdapter(_FEEDBACK_FLOW)
        self.complete = CompleteStepUseCase(
            self.store, adapter, worktrees=NoopWorktrees(), config=None)
        self.uc = DispatchPrFeedbackUseCase(
            self.store, github, adapter, self.complete,
            trusted_authors=lambda: frozenset(trusted),
            review_bots=lambda: frozenset(review_bots),
            held_shortcode=lambda: "HLD", poll_epoch=lambda: 0, unread_note_polls=lambda: 3,
        )
        return self.uc

    def _feedback_steps(self):
        return [
            n for n in self.store.all_nodes()
            if n.type == "step" and n.stage == "handle-feedback"
        ]

    def _gates(self):
        return [
            n for n in self.store.all_nodes_including_done()
            if n.type == "step" and n.stage == "review-held-comment"
        ]

    def _admitted(self, step_id):
        found = [a for a in self.store.item_artifacts(step_id) if a.type == "admitted-comments"]
        return found[0].value.split("\n") if found else None

    def _finish_feedback(self):
        for s in self._feedback_steps():
            self.store.complete_node(s.id, "done")


class TestOperatorRouting(_Rig):
    def test_an_operator_inline_reply_without_the_token_routes_nothing(self):
        self._build(FakeGitHub(push_time=1000.0, timed_comments=[
            _inline(1200.0, _OUTSIDER, "root"),
            _inline(1300.0, _OPERATOR, "reply", in_reply_to="root", body="thanks, will do"),
        ]))
        self.uc.execute()
        self.assertEqual(self._feedback_steps(), [])
        self.assertEqual(len(self._gates()), 1)

    def test_an_operator_inline_reply_with_the_token_opens_a_step(self):
        self._build(FakeGitHub(push_time=1000.0, timed_comments=[
            _inline(1200.0, _OUTSIDER, "root"),
            _inline(1300.0, _OPERATOR, "reply", in_reply_to="root", body="@lc do it"),
        ]))
        self.uc.execute()
        (step,) = self._feedback_steps()
        self.assertEqual(self._admitted(step.id), ["inline:reply"])

    def test_an_operator_inline_root_and_review_need_the_token(self):
        for body, expected in (("plain", 0), ("@lc fix", 1)):
            with self.subTest(body=body):
                self._build(FakeGitHub(push_time=1000.0, timed_comments=[
                    _inline(1200.0, _OPERATOR, "root", body=body)]))
                self.uc.execute()
                self.assertEqual(len(self._feedback_steps()), expected)
                self._build(FakeGitHub(push_time=1000.0, timed_reviews=[
                    _review(1200.0, _OPERATOR, "rv", body=body)]))
                self.uc.execute()
                self.assertEqual(len(self._feedback_steps()), expected)

    def test_only_the_operator_comment_with_the_token_is_admitted(self):
        self._build(FakeGitHub(push_time=1000.0, timed_comments=[
            _inline(1200.0, _OPERATOR, "a"),
            _inline(1210.0, _OPERATOR, "b", body="@lc yes"),
            _inline(1220.0, _OPERATOR, "c", body="fine"),
        ]))
        self.uc.execute()
        (step,) = self._feedback_steps()
        self.assertEqual(self._admitted(step.id), ["inline:b"])
        self.assertEqual(self._gates(), [])

    def test_a_top_level_mention_by_an_operator_still_opens_a_step(self):
        self._build(FakeGitHub(push_time=1000.0, timed_comments=[
            _top(1200.0, _OPERATOR, "m1", body="@lc please fix")]))
        self.assertEqual(self.uc.execute().reworked, [self.item])


class TestReviewBots(_Rig):
    def test_a_review_bot_routes_without_the_token(self):
        self._build(FakeGitHub(push_time=1000.0, timed_comments=[_inline(1200.0, _BOT, "b1")]))
        self.assertEqual(self.uc.execute().reworked, [self.item])

    def test_a_review_bot_listed_but_not_trusted_is_gated(self):
        self._build(
            FakeGitHub(push_time=1000.0, timed_comments=[_inline(1200.0, "ghost", "b1")]),
            review_bots=("ghost",))
        self.assertEqual(self.uc.execute().reworked, [])
        self.assertEqual(len(self._gates()), 1)

    def test_an_operators_reply_does_not_displace_a_bots_root(self):
        self._build(FakeGitHub(push_time=1000.0, timed_comments=[
            _inline(1200.0, _BOT, "root"),
            _inline(1300.0, _OPERATOR, "reply", in_reply_to="root", body="ok"),
        ]))
        self.uc.execute()
        (step,) = self._feedback_steps()
        self.assertEqual(self._admitted(step.id), ["inline:root"])


class TestGatesForEveryNonTrustedComment(_Rig):
    def test_every_non_trusted_comment_kind_files_exactly_one_gate(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _inline(1200.0, _OUTSIDER, "root"),
            _inline(1210.0, _OUTSIDER, "reply", in_reply_to="root"),
            _top(1220.0, _OUTSIDER, "top"),
            _inline(1230.0, _OUTSIDER, "marked", body="engine %s" % LC_MARKER),
            _inline(1240.0, _OPERATOR, "mine", body="no instruction here"),
        ], timed_reviews=[
            _review(1250.0, _OUTSIDER, "rv1", body="summary", state="COMMENTED"),
            _review(1260.0, _OUTSIDER, "rv2", body="", state="CHANGES_REQUESTED"),
        ])
        self._build(gh)
        self.uc.execute()
        self.uc.execute()
        self.assertEqual(len(self._gates()), 6)
        self.assertEqual(self._feedback_steps(), [])


class TestLiveRereadOfGates(_Rig):
    def _gated(self, *comments):
        self._build(FakeGitHub(push_time=1000.0, timed_comments=list(comments)))
        self.uc.execute()
        (gate,) = self._gates()
        return gate

    def test_an_edited_comment_updates_its_open_gate(self):
        gate = self._gated(_inline(1200.0, _OUTSIDER, "root", body="first words"))
        self.github._timed_comments = [_inline(1200.0, _OUTSIDER, "root", body="second words")]
        self.uc.execute()
        self.assertEqual(len(self._gates()), 1)
        item = self.store.get_item(gate.item)
        self.assertIn("second words", item.description)
        self.assertNotIn("first words", item.description)
        self.assertIn("Edited by the reviewer since first seen", item.description)
        self.assertEqual(held_comment(self.store, self.rid, "inline:root").body, "second words")

    def test_a_deleted_comment_withdraws_its_gate(self):
        gate = self._gated(_inline(1200.0, _OUTSIDER, "root"))
        self.github._timed_comments = []
        self.uc.execute()
        self.assertEqual(held_comment(self.store, self.rid, "inline:root").state, "withdrawn")
        self.assertEqual(self.store.get_node(gate.id).state, State.DONE)

    def test_a_failed_read_does_not_withdraw_a_gate(self):
        gate = self._gated(_inline(1200.0, _OUTSIDER, "root"))
        self.github._timed_comments = []
        for failure in ({"pull_comments"}, None):
            with self.subTest(failure=failure):
                if failure:
                    self.github._failing_calls = failure
                else:
                    self.github.pull_comments = lambda pr, since: NotYetRead()
                    self.github._failing_calls = set()
                self.uc.execute()
                self.assertEqual(held_comment(self.store, self.rid, "inline:root").state, "held")
                self.assertNotEqual(self.store.get_node(gate.id).state, State.DONE)
                self.assertIn("review-gates:", self.store.get_node(self.step).notes or "")

    def test_an_operator_reply_in_the_thread_supersedes_the_gate(self):
        gate = self._gated(_inline(1200.0, _OUTSIDER, "root"))
        self.github._timed_comments.append(
            _inline(1300.0, _OPERATOR, "reply", in_reply_to="root", body="thanks, fixed"))
        self.uc.execute()
        self.assertEqual(held_comment(self.store, self.rid, "inline:root").state, "superseded")
        self.assertEqual(self.store.get_node(gate.id).state, State.DONE)
        self.assertEqual(self._feedback_steps(), [])

    def test_an_engine_marked_reply_does_not_supersede(self):
        self._gated(_inline(1200.0, _OUTSIDER, "root"))
        self.github._timed_comments.append(_inline(
            1300.0, _OPERATOR, "reply", in_reply_to="root",
            body="%s pushed %s" % (AUTOMATED_PREFIX, LC_MARKER)))
        self.uc.execute()
        self.assertEqual(held_comment(self.store, self.rid, "inline:root").state, "held")


class TestCompletingAGate(_Rig):
    def test_approve_is_refused_with_the_at_lc_instruction(self):
        self._build(FakeGitHub(push_time=1000.0, timed_comments=[_top(1200.0, _OUTSIDER, "t")]))
        self.uc.execute()
        (gate,) = self._gates()
        with self.assertRaises(UseCaseError) as caught:
            self.complete.execute(CompleteInput(step=gate.id, outcome="approve"))
        self.assertIn("@lc", str(caught.exception))
        self.assertEqual(held_comment(self.store, self.rid, "mention:t").state, "held")

    def test_the_engine_only_outcomes_are_refused_to_a_person(self):
        self._build(FakeGitHub(push_time=1000.0, timed_comments=[_top(1200.0, _OUTSIDER, "t")]))
        self.uc.execute()
        (gate,) = self._gates()
        for outcome in ("superseded", "withdrawn"):
            with self.assertRaises(UseCaseError):
                self.complete.execute(CompleteInput(step=gate.id, outcome=outcome))

    def test_dealt_and_reject_close_it(self):
        for outcome, state in (("dealt", "dealt"), ("reject", "rejected")):
            with self.subTest(outcome=outcome):
                self._build(FakeGitHub(
                    push_time=1000.0, timed_comments=[_top(1200.0, _OUTSIDER, "t")]))
                self.uc.execute()
                (gate,) = self._gates()
                self.complete.execute(CompleteInput(step=gate.id, outcome=outcome))
                self.assertEqual(held_comment(self.store, self.rid, "mention:t").state, state)


class TestTheReadWindow(_Rig):
    def test_a_comment_posted_during_a_rework_is_admitted_after_the_push(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _top(1200.0, _OPERATOR, "a", body="@lc one")])
        self._build(gh)
        self.assertEqual(self.uc.execute().reworked, [self.item])
        gh._timed_comments.append(_top(1300.0, _OPERATOR, "b", body="@lc two"))
        self.assertEqual(self.uc.execute().reworked, [])
        self._finish_feedback()
        gh._push_time = 1500.0
        self.assertEqual(self.uc.execute().reworked, [self.item])
        (step,) = self._feedback_steps()
        self.assertEqual(self._admitted(step.id), ["mention:b"])

    def test_a_comment_in_the_same_second_as_the_watermark_is_admitted_once(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _top(1200.0, _OPERATOR, "a", body="@lc one")])
        self._build(gh)
        self.uc.execute()
        self._finish_feedback()
        gh._timed_comments.append(_top(1200.0, _OPERATOR, "b", body="@lc two"))
        gh._push_time = 1500.0
        self.assertEqual(self.uc.execute().reworked, [self.item])
        (step,) = self._feedback_steps()
        self.assertEqual(self._admitted(step.id), ["mention:b"])

    def test_the_window_falls_back_to_the_last_push_before_any_dispatch(self):
        class _Run:
            comments_dispatched_through = None

        self.assertEqual(feedback_window_start(_Run(), 1000.0), 1000.0)

    def test_the_idle_check_sees_a_pending_comment(self):
        from tests.unit.test_skip_idle_ci_watch import _Rig as _CiRig, _gh, _comment, _PUSH

        rig = _CiRig(_gh(comments=[(_PUSH + 50, _comment(body="@lc fix"))]))
        run = rig.store.current_run(rig.item, None)
        rig.store.set_comments_dispatched_through(run.id, str(_PUSH + 10))
        rig.uc.execute()
        self.assertEqual(rig.step("watch-ci").state, State.QUEUED)
