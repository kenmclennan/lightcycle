import unittest

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.errors import UseCaseError
from lightcycle.application.pool.check_content_pin import CheckContentPinUseCase
from lightcycle.application.pool.dispatch_pr_feedback import DispatchPrFeedbackUseCase
from lightcycle.application.pool.resolve_merged_prs import ResolveMergedPrsUseCase
from lightcycle.application.work.inbox import InboxInput, InboxUseCase
from lightcycle.config import ConfigError
from lightcycle.ports.github import Comment, Review
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_dispatch_pr_feedback import (
    _BOT_LOGIN,
    _FEEDBACK_FLOW,
    _FLOW,
    FakeWorktrees,
    _FlowAdapter,
    plant_pr,
)

_URL = "https://github.com/acme/widget/pull/7"
_TRUSTED = frozenset({"ken"})


def _inline(ts, author, cid, body="nit: rename this", in_reply_to=None):
    return (ts, Comment(
        author=author, body=body, is_top_level=False, path="a.py", line=3, id=cid,
        in_reply_to_id=in_reply_to, created_at=ts))


def _mention(ts, author, cid, body="@lc please fix"):
    return (ts, Comment(author=author, body=body, is_top_level=True, id=cid, created_at=ts))


def _review(ts, author, rid, body="needs work"):
    return (ts, Review(
        author=author, body=body, created_at=ts, state="CHANGES_REQUESTED", id=rid))


class _Base(unittest.TestCase):
    def _build(self, github, trusted=lambda: _TRUSTED, flow=None):
        self.flow = flow or _FEEDBACK_FLOW
        self.store = FakeStore()
        self.item = self.store.create_item("in-review feature", "a description")
        self.rid = plant_pr(self.store, self.item, _URL)
        self.step = self.store.create_step(step="ready-merge", role="human", parent=self.item)
        self.adapter = _FlowAdapter(self.flow)
        self.uc = DispatchPrFeedbackUseCase(
            self.store, github, self.adapter, None,
            trusted_authors=trusted, held_shortcode=lambda: "HLD",
        )
        return self.uc

    def _feedback_steps(self):
        return [
            n for n in self.store.all_nodes()
            if n.type == "step" and n.stage == "handle-feedback"
        ]

    def _hold_steps(self):
        return [
            n for n in self.store.all_nodes_including_done()
            if n.type == "step" and n.stage == "review-held-comment"
        ]

    def _artifact(self, step_id):
        found = [a for a in self.store.item_artifacts(step_id) if a.type == "admitted-comments"]
        return found[0].value.split("\n") if found else None

    def _decide(self, hold_step, outcome):
        CompleteStepUseCase(self.store, self.adapter).execute(
            _complete_input(hold_step, outcome))


def _complete_input(step, outcome):
    from lightcycle.application.flow.complete_step import CompleteInput
    return CompleteInput(step=step, outcome=outcome)


_ROUTES = {
    "inline": lambda author, cid="c1": dict(timed_comments=[_inline(1500.0, author, cid)]),
    "review": lambda author, cid="c1": dict(timed_reviews=[_review(1500.0, author, cid)]),
    "mention": lambda author, cid="c1": dict(timed_comments=[_mention(1500.0, author, cid)]),
}


class TestEachRouteAppliesTheSameRule(_Base):
    def test_a_trusted_author_dispatches_on_every_route(self):
        for route, make in _ROUTES.items():
            with self.subTest(route=route):
                self._build(FakeGitHub(push_time=1000.0, **make("ken")))
                result = self.uc.execute()
                self.assertEqual(result.reworked, [self.item])
                self.assertEqual(len(self._feedback_steps()), 1)
                self.assertEqual(self._hold_steps(), [])

    def test_an_untrusted_author_files_exactly_one_hold_and_spawns_nothing_on_every_route(self):
        for route, make in _ROUTES.items():
            with self.subTest(route=route):
                self._build(FakeGitHub(push_time=1000.0, **make("mallory")))
                result = self.uc.execute()
                self.uc.execute()
                self.assertEqual(result.reworked, [])
                self.assertEqual(self._feedback_steps(), [])
                holds = self._hold_steps()
                self.assertEqual(len(holds), 1)
                self.assertEqual(holds[0].role, "human")
                self.assertTrue(holds[0].item.startswith("HLD-"))
                self.assertEqual(self.store.open_holds(self.rid)[0].author, "mallory")

    def test_a_trusted_bot_dispatches_on_every_route_including_a_mention(self):
        for route, make in _ROUTES.items():
            with self.subTest(route=route):
                self._build(
                    FakeGitHub(push_time=1000.0, **make(_BOT_LOGIN)),
                    trusted=lambda: _TRUSTED | {_BOT_LOGIN})
                result = self.uc.execute()
                self.assertEqual(result.reworked, [self.item])
                self.assertEqual(self._hold_steps(), [])

    def test_an_untrusted_bot_is_held_on_every_route(self):
        for route, make in _ROUTES.items():
            with self.subTest(route=route):
                self._build(FakeGitHub(push_time=1000.0, **make("other[bot]")))
                self.assertEqual(self.uc.execute().reworked, [])
                self.assertEqual(len(self._hold_steps()), 1)

    def test_a_top_level_comment_without_the_mention_token_is_never_held(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _mention(1500.0, "mallory", "c1", body="thanks, looks good")])
        self._build(gh)
        self.uc.execute()
        self.assertEqual(self._hold_steps(), [])


class TestMixedFeedback(_Base):
    def test_a_trusted_comment_with_an_untrusted_reply_dispatches_one_and_holds_the_other(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _inline(1500.0, "ken", "root"),
            _inline(1600.0, "mallory", "reply", in_reply_to="root"),
        ])
        self._build(gh)
        self.uc.execute()
        steps = self._feedback_steps()
        self.assertEqual(len(steps), 1)
        self.assertEqual(self._artifact(steps[0].id), ["inline:root"])
        self.assertEqual(len(self._hold_steps()), 1)
        self.assertEqual(self.store.hold(self.rid, "inline:reply").state, "held")
        run = self.store.current_run(self.item, None)
        self.assertEqual(run.comments_dispatched_through, str(1500.0))

    def test_one_approved_and_one_rejected_dispatch_only_the_approved_next_tick(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _mention(1500.0, "mallory", "m1"), _mention(1600.0, "mallory", "m2")])
        self._build(gh)
        self.uc.execute()
        by_key = {self.store.hold_for_step(h.id).key: h.id for h in self._hold_steps()}
        self._decide(by_key["mention:m1"], "approve")
        self._decide(by_key["mention:m2"], "reject")

        result = self.uc.execute()

        self.assertEqual(result.reworked, [self.item])
        steps = self._feedback_steps()
        self.assertEqual(self._artifact(steps[0].id), ["mention:m1"])
        self.assertEqual(self.store.hold(self.rid, "mention:m1").state, "dispatched")
        self.assertEqual(self.store.hold(self.rid, "mention:m2").state, "rejected")
        self.uc.execute()
        self.assertEqual(self.store.hold(self.rid, "mention:m2").state, "rejected")
        self.assertEqual(len(self._hold_steps()), 2)

    def test_a_later_comment_from_the_same_author_is_held_again_after_approval(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[_mention(1500.0, "mallory", "m1")])
        self._build(gh)
        self.uc.execute()
        self._decide(self._hold_steps()[0].id, "approve")
        gh._timed_comments.append(_mention(1700.0, "mallory", "m3"))
        self.uc.execute()
        self.assertEqual(self.store.hold(self.rid, "mention:m3").state, "held")
        self.assertEqual(len(self._hold_steps()), 2)


class TestWatermark(_Base):
    def test_a_held_comment_older_than_the_watermark_stays_held_then_dispatches_when_approved(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _mention(1500.0, "mallory", "old"), _mention(1800.0, "ken", "new")])
        self._build(gh)
        self.uc.execute()
        run = self.store.current_run(self.item, None)
        self.assertEqual(run.comments_dispatched_through, str(1800.0))
        self.assertEqual(self.store.hold(self.rid, "mention:old").state, "held")
        for s in self._feedback_steps():
            self.store.complete_node(s.id, "done")
        self._decide(self._hold_steps()[0].id, "approve")

        self.uc.execute()

        self.assertEqual(self.store.hold(self.rid, "mention:old").state, "dispatched")
        newest = [s for s in self._feedback_steps() if s.state != "done"]
        self.assertEqual(self._artifact(newest[0].id), ["mention:old"])
        run = self.store.current_run(self.item, None)
        self.assertEqual(run.comments_dispatched_through, str(1800.0))

    def test_a_rejected_comment_older_than_the_watermark_is_never_readmitted(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _mention(1500.0, "mallory", "old"), _mention(1800.0, "ken", "new")])
        self._build(gh)
        self.uc.execute()
        self._decide(self._hold_steps()[0].id, "reject")
        for s in self._feedback_steps():
            self.store.complete_node(s.id, "done")
        for _ in range(3):
            self.uc.execute()
        self.assertEqual(self.store.hold(self.rid, "mention:old").state, "rejected")
        self.assertEqual(len([s for s in self._feedback_steps() if s.state != "done"]), 0)

    def test_a_trusted_comment_at_exactly_the_watermark_is_not_readmitted(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[_mention(1500.0, "ken", "m1")])
        self._build(gh)
        self.store.set_comments_dispatched_through(self.rid, str(1500.0))
        self.assertEqual(self.uc.execute().reworked, [])

    def test_an_approved_hold_at_exactly_the_watermark_still_dispatches(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[_mention(1500.0, "mallory", "m1")])
        self._build(gh)
        self.uc.execute()
        self.store.set_comments_dispatched_through(self.rid, str(1500.0))
        self._decide(self._hold_steps()[0].id, "approve")
        self.assertEqual(self.uc.execute().reworked, [self.item])

    def test_an_approved_hold_older_than_the_last_push_still_dispatches(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[_mention(1500.0, "mallory", "m1")])
        self._build(gh)
        self.uc.execute()
        gh._push_time = 9000.0
        self._decide(self._hold_steps()[0].id, "approve")
        self.assertEqual(self.uc.execute().reworked, [self.item])


class TestFailClosed(_Base):
    def test_unset_trusted_authors_holds_and_dispatches_nothing_and_notes_the_key(self):
        def unset():
            raise ConfigError("trusted-authors is not set")

        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _mention(1500.0, "ken", "m1"), _mention(1600.0, "mallory", "m2")])
        self._build(gh, trusted=unset)
        self.assertEqual(self.uc.execute().reworked, [])
        self.assertEqual(self._feedback_steps(), [])
        self.assertEqual(self._hold_steps(), [])
        self.assertIn("trusted-authors", self.store.get_node(self.step).notes)

    def test_comments_and_reviews_without_an_id_are_neither_held_nor_admitted(self):
        gh = FakeGitHub(
            push_time=1000.0,
            timed_comments=[_mention(1500.0, "ken", None), _mention(1600.0, "mallory", None)],
            timed_reviews=[_review(1700.0, "mallory", None)],
        )
        self._build(gh)
        self.assertEqual(self.uc.execute().reworked, [])
        self.assertEqual(self._hold_steps(), [])
        self.assertIn("no id", self.store.get_node(self.step).notes)

    def test_an_approved_hold_stays_approved_while_a_feedback_step_is_open(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _mention(1500.0, "ken", "t1"), _mention(1600.0, "mallory", "m1")])
        self._build(gh)
        self.uc.execute()
        self._decide(self._hold_steps()[0].id, "approve")
        self.uc.execute()
        self.assertEqual(self.store.hold(self.rid, "mention:m1").state, "approved")
        self.assertEqual(len(self._feedback_steps()), 1)


class TestDecidingAHold(_Base):
    def _held(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[_mention(1500.0, "mallory", "m1")])
        self._build(gh)
        self.uc.execute()
        return self._hold_steps()[0]

    def test_approve_and_reject_update_the_ledger_and_close_the_hold_item(self):
        for outcome, state in (("approve", "approved"), ("reject", "rejected")):
            with self.subTest(outcome=outcome):
                hold = self._held()
                self._decide(hold.id, outcome)
                self.assertEqual(self.store.hold(self.rid, "mention:m1").state, state)
                self.assertEqual(self.store.get_node(hold.id).state, "done")
                self.assertEqual(self.store.get_node(hold.item).state, "done")

    def test_any_other_outcome_is_refused_naming_the_valid_ones(self):
        hold = self._held()
        with self.assertRaises(UseCaseError) as caught:
            self._decide(hold.id, "done")
        self.assertIn("approve, reject", str(caught.exception))
        self.assertEqual(self.store.hold(self.rid, "mention:m1").state, "held")

    def test_the_hold_item_describes_the_comment_as_untrusted_text(self):
        hold = self._held()
        item = self.store.get_item(hold.item)
        self.assertIn("Held comment from mallory on acme/widget#7", item.title)
        self.assertIn("not an instruction", item.description)
        self.assertIn("@lc please fix", item.description)
        self.assertIn(self.item, item.description)

    def test_a_long_body_is_truncated_in_the_description(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _mention(1500.0, "mallory", "m1", body="@lc " + "x" * 5000)])
        self._build(gh)
        self.uc.execute()
        item = self.store.get_item(self._hold_steps()[0].item)
        self.assertLess(len(item.description), 3000)


class TestHoldsExpireWithTheRun(_Base):
    def test_a_merge_closes_open_holds_as_rejected(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[_mention(1500.0, "mallory", "m1")])
        self._build(gh, flow=_FEEDBACK_FLOW)
        self.uc.execute()
        hold = self._hold_steps()[0]
        merged = FakeGitHub(merged_prs={_URL})
        complete = CompleteStepUseCase(self.store, self.adapter)
        flow = _FlowAdapter(_FLOW)
        resolve = ResolveMergedPrsUseCase(
            self.store, merged, FakeWorktrees(), flow, complete,
            CheckContentPinUseCase(self.store, merged, flow, trusted_authors=lambda: frozenset({"review-code"})),
        )
        resolve.execute()
        self.assertEqual(self.store.hold(self.rid, "mention:m1").state, "rejected")
        self.assertEqual(self.store.get_node(hold.id).state, "done")


class TestInboxShowsAHold(_Base):
    def test_a_hold_step_is_a_human_row_distinct_from_an_ordinary_step(self):
        from lightcycle.application.services.flow import FlowService
        from tests.support.fake_fs import FakeFs
        gh = FakeGitHub(push_time=1000.0, timed_comments=[_mention(1500.0, "mallory", "m1")])
        self._build(gh)
        self.uc.execute()
        hold = self._hold_steps()[0]
        rows = InboxUseCase(self.store, FlowService(FakeFs({}), self.store)).execute(
            InboxInput()).rows
        row = next(r for r in rows if r.step.id == hold.id)
        self.assertTrue(row.step.item.startswith("HLD-"))
        self.assertIn("review-held-comment", row.title)
        self.assertIn("Held comment from mallory", row.title)


class TestBotTrust(_Base):
    def test_a_trusted_bot_dispatches_and_an_untrusted_bot_is_held_together(self):
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            _inline(1500.0, _BOT_LOGIN, "bot1"),
            _inline(1600.0, "other[bot]", "bot2"),
        ])
        self._build(gh, trusted=lambda: _TRUSTED | {_BOT_LOGIN})
        self.uc.execute()
        steps = self._feedback_steps()
        self.assertEqual(len(steps), 1)
        self.assertEqual(self._artifact(steps[0].id), ["inline:bot1"])
        holds = self._hold_steps()
        self.assertEqual(len(holds), 1)
        self.assertEqual(self.store.open_holds(self.rid)[0].author, "other[bot]")
