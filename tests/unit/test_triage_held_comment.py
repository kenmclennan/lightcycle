import datetime
import os
import unittest

from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.pool.dispatch_pr_feedback import DispatchPrFeedbackUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.config import Config
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.null_collaborators import NoopWorktrees
from tests.support.store_seed import held_comment
from tests.unit.test_dispatch_pr_feedback import _FEEDBACK_FLOW, _FlowAdapter, plant_pr
from tests.unit.test_dispatch_trust import _inline, _mention

_URL = "https://github.com/acme/widget/pull/7"
_TRIAGE = "triage-held-comment"
_GATE = "review-held-comment"
_PROMPT = os.path.join(
    os.path.dirname(__file__), "..", "..", "lightcycle", "prompts", "steps", "triage-held-comment.md")


class _Rig(unittest.TestCase):
    def _build(self, github, timeout=900):
        self.store = FakeStore()
        self.item = self.store.create_item("in-review feature", "a description")
        self.rid = plant_pr(self.store, self.item, _URL)
        self.store.create_step(stage="ready-merge", role="human", item=self.item)
        self.adapter = _FlowAdapter(_FEEDBACK_FLOW)
        self.clock = 0.0
        self.timeout = timeout
        self.uc = DispatchPrFeedbackUseCase(
            self.store, github, self.adapter, self._complete(),
            trusted_authors=lambda: frozenset({"ken"}), review_bots=lambda: frozenset({"ken"}),
            held_shortcode=lambda: "HLD", held_triage_timeout=lambda: self.timeout,
            wall_clock=lambda: self.clock, poll_epoch=lambda: 0, unread_note_polls=lambda: 3,
        )

    def _complete(self):
        return CompleteStepUseCase(
            self.store, self.adapter, worktrees=NoopWorktrees(), config=None)

    def _steps(self, stage):
        return [
            n for n in self.store.all_nodes_including_done()
            if n.type == "step" and n.stage == stage
        ]

    def _close(self, step, outcome, note=None, by_engine=False):
        self._complete().execute(
            CompleteInput(step=step, outcome=outcome, note=note, by_engine=by_engine))

    def _quiet_artifacts(self):
        return [a for a in self.store.item_artifacts(self.item) if a.type == "quiet-comment"]


def _one(author="mallory", cid="c1"):
    return FakeGitHub(push_time=1000.0, timed_comments=[_mention(1500.0, author, cid)])


class TestTriageFiling(_Rig):
    def test_a_non_inline_hold_files_a_triage_step_not_a_gate(self):
        self._build(_one())
        self.uc.execute()
        self.assertEqual(len(self._steps(_TRIAGE)), 1)
        self.assertEqual(self._steps(_GATE), [])

    def test_an_inline_hold_files_the_gate_directly(self):
        self._build(FakeGitHub(push_time=1000.0, timed_comments=[_inline(1500.0, "mallory", "c1")]))
        self.uc.execute()
        self.assertEqual(len(self._steps(_GATE)), 1)
        self.assertEqual(self._steps(_TRIAGE), [])

    def test_timeout_zero_files_the_gate_directly(self):
        self._build(_one(), timeout=0)
        self.uc.execute()
        self.assertEqual(len(self._steps(_GATE)), 1)
        self.assertEqual(self._steps(_TRIAGE), [])


class TestTriageOutcomes(_Rig):
    def test_asks_files_the_gate_and_repoints_the_hold(self):
        self._build(_one())
        self.uc.execute()
        (triage,) = self._steps(_TRIAGE)
        self._close(triage.id, "asks", "it asks a question")
        (gate,) = self._steps(_GATE)
        self.assertEqual(gate.item, triage.item)
        self.assertEqual(gate.role, "human")
        hold = held_comment(self.store, self.rid, "mention:c1")
        self.assertEqual(hold.step_id, gate.id)
        self.assertEqual(hold.state, "held")

    def test_quiet_notes_the_hold_and_records_the_reason(self):
        self._build(_one())
        self.uc.execute()
        (triage,) = self._steps(_TRIAGE)
        self.assertEqual(self._quiet_artifacts(), [])
        self._close(triage.id, "quiet", "a clean scan summary")
        hold = held_comment(self.store, self.rid, "mention:c1")
        self.assertEqual(hold.state, "noted")
        self.assertEqual(self.store.get_node(triage.item).state, "done")
        self.assertEqual(self._steps(_GATE), [])
        (artifact,) = self._quiet_artifacts()
        for part in ("mallory", "mention:c1", "a clean scan summary", "acme/widget#7"):
            self.assertIn(part, artifact.value)

    def test_a_quiet_comment_is_not_triaged_again(self):
        self._build(_one())
        self.uc.execute()
        (triage,) = self._steps(_TRIAGE)
        self._close(triage.id, "quiet", "a version stamp")
        self.uc.execute()
        self.assertEqual(len(self._steps(_TRIAGE)), 1)
        self.assertEqual(self._steps(_GATE), [])

    def test_a_mixed_dispatch_gates_only_the_comment_that_asks(self):
        self._build(FakeGitHub(push_time=1000.0, timed_comments=[
            _mention(1500.0, "mallory", "c1"), _mention(1501.0, "mallory", "c2")]))
        self.uc.execute()
        first, second = sorted(self._steps(_TRIAGE), key=lambda n: n.id)
        quiet_key = held_comment(self.store, self.rid, "mention:c1").step_id
        quiet, asks = (first, second) if first.id == quiet_key else (second, first)
        self._close(quiet.id, "quiet", "LGTM with nothing asked")
        self._close(asks.id, "asks", "a blocker")
        self.assertEqual(len(self._steps(_GATE)), 1)
        states = sorted(
            held_comment(self.store, self.rid, k).state for k in ("mention:c1", "mention:c2"))
        self.assertEqual(states, ["held", "noted"])
        self.assertEqual(len(self._quiet_artifacts()), 1)

    def test_all_quiet_opens_no_gate_and_all_asks_opens_one_each(self):
        for outcome, gates in (("quiet", 0), ("asks", 2)):
            with self.subTest(outcome=outcome):
                self._build(FakeGitHub(push_time=1000.0, timed_comments=[
                    _mention(1500.0, "mallory", "c1"), _mention(1501.0, "bot", "c2")]))
                self.uc.execute()
                for triage in self._steps(_TRIAGE):
                    self._close(triage.id, outcome, "reason")
                self.assertEqual(len(self._steps(_GATE)), gates)

    def test_withdrawn_superseded_and_reject_close_a_triage_step(self):
        for outcome, state in (
            ("withdrawn", "withdrawn"), ("superseded", "superseded"), ("reject", "rejected"),
        ):
            with self.subTest(outcome=outcome):
                self._build(_one())
                self.uc.execute()
                (triage,) = self._steps(_TRIAGE)
                self._close(triage.id, outcome, "engine", by_engine=True)
                self.assertEqual(held_comment(self.store, self.rid, "mention:c1").state, state)
                self.assertEqual(self.store.get_node(triage.id).state, "done")

    def test_an_unlisted_outcome_is_refused_with_the_valid_list(self):
        self._build(_one())
        self.uc.execute()
        (triage,) = self._steps(_TRIAGE)
        for outcome in ("approve", "dealt", "bogus"):
            with self.subTest(outcome=outcome):
                with self.assertRaises(UseCaseError) as ctx:
                    self._close(triage.id, outcome)
                self.assertIn("asks, quiet", str(ctx.exception))
        self.assertNotEqual(self.store.get_node(triage.id).state, "done")


class TestTriageDeadline(_Rig):
    def _created(self, step):
        return datetime.datetime.fromisoformat(self.store.get_node(step.id).created_at).timestamp()

    def _assert_became_a_gate(self, triage):
        self.assertEqual(self.store.get_node(triage.id).state, "done")
        self.assertEqual(self.store.get_node(triage.id).report, "triage did not finish")
        self.assertEqual(len(self._steps(_GATE)), 1)

    def test_a_fresh_queued_triage_step_is_left_alone(self):
        self._build(_one())
        self.uc.execute()
        (triage,) = self._steps(_TRIAGE)
        self.clock = self._created(triage) + 10
        self.uc.execute()
        self.assertNotEqual(self.store.get_node(triage.id).state, "done")
        self.assertEqual(self._steps(_GATE), [])

    def test_a_parked_triage_step_becomes_a_gate(self):
        self._build(_one())
        self.uc.execute()
        (triage,) = self._steps(_TRIAGE)
        ParkStepUseCase(self.store).execute(
            ParkInput(step=triage.id, observation="the agent failed", decision="a human decides"))
        self.clock = self._created(triage) + 1
        self.uc.execute()
        self._assert_became_a_gate(triage)

    def test_an_expired_triage_step_becomes_a_gate(self):
        self._build(_one())
        self.uc.execute()
        (triage,) = self._steps(_TRIAGE)
        self.clock = self._created(triage) + 901
        self.uc.execute()
        self._assert_became_a_gate(triage)


class TestTriagePrompt(unittest.TestCase):
    def test_the_committed_prompt_is_sonnet_and_names_no_author(self):
        service = FlowService(WorkflowBundleAdapter(), FakeStore(), config=Config(environ={}))
        self.assertEqual(service.meta_for_unpinned_step(_TRIAGE).get("model"), "sonnet")
        text = open(_PROMPT).read()
        self.assertTrue(text.startswith("---\nmodel: sonnet\n---"))
        self.assertNotIn("[bot]", text)
        self.assertNotIn("trusted-authors", text)
        self.assertIn("asks", text)
        self.assertIn("quiet", text)
