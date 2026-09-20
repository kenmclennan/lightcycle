import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

from lightcycle import cli
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.complete_step import CompleteInput, CompleteStepUseCase
from lightcycle.application.flow.engine_steps import GOAL_STATE_OF_PLAY_STEP, SUMMARY_ORIGIN_LABEL
from lightcycle.application.goals import RefreshGoalStateOfPlayUseCase, assemble_goal_context
from lightcycle.application.work.closed_count import closed_count
from lightcycle.application.work.link_artifact import LinkArtifactInput, LinkArtifactUseCase
from lightcycle.application.workflows.prompt_commands import lc_calls
from lightcycle.domain.work import State
from lightcycle.domain.work.worker_permissions import WORKER_VERBS
from tests.support.fake_store import FakeStore
from tests.unit.test_flow_usecases import METAS, flow_for

PROMPT = os.path.join(
    os.path.dirname(__file__), "..", "..", "lightcycle", "prompts", "steps", "goal-state-of-play.md"
)


class FakeConfig:
    def summary_shortcode(self):
        return "SUM"


def _complete(store, step, outcome="done"):
    return CompleteStepUseCase(store, flow_for(METAS, store)).execute(
        CompleteInput(step=step, outcome=outcome))


def _attach_summary(store, step, text):
    LinkArtifactUseCase(store).execute(LinkArtifactInput(item=step, atype="summary", value=text))


class _Base(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.gid = self.store.create_goal("the goal", "the problem", "lightcycle")
        self.uc = RefreshGoalStateOfPlayUseCase(self.store, FakeConfig())

    def snapshot(self):
        g = self.store.get_goal(self.gid)
        return (
            self.store.goal_log(self.gid), self.store.goal_items(self.gid),
            g.description, g.updated_at,
        )


class TestAssembler(_Base):
    def test_sections_in_order_with_the_log_oldest_first_and_description_verbatim(self):
        self.store.update_goal(self.gid, description="line one\n\nline two")
        self.store.add_goal_log(self.gid, "first title", "first body")
        self.store.add_goal_log(self.gid, "second title", "second body")

        text = assemble_goal_context(self.store, self.gid)

        marks = [
            "Goal %s: the goal" % self.gid, "line one\n\nline two", "first title",
            "first body", "second title", "second body", "## Open items", "## Done items",
        ]
        positions = [text.index(m) for m in marks]
        self.assertEqual(positions, sorted(positions))

    def test_a_wiki_link_in_the_description_reaches_the_generator_with_its_title(self):
        item = self.store.create_item(
            "the gate can suspend the last working worker", "d", shortcode="LC")
        self.store.update_goal(
            self.gid, description="## Constraints\n- keep [[%s]] intact\n- and [[LC-99999]]" % item)

        text = assemble_goal_context(self.store, self.gid)

        self.assertIn(
            "## Constraints\n- keep the gate can suspend the last working worker (%s) intact" % item,
            text)
        self.assertIn("- and LC-99999 (not found)", text)
        self.assertNotIn("[[", text)

    def test_no_linked_items_reads_none_in_both_sections(self):
        text = assemble_goal_context(self.store, self.gid)

        self.assertIn("## Open items\n(none)", text)
        self.assertIn("## Done items\n(none)", text)

    def test_open_closed_and_deleted_items_each_appear_once_in_their_section(self):
        open_item = self.store.create_item("still to do", "d")
        closed_item = self.store.create_item("finished", "d")
        self.store.complete_node(closed_item, "merged", disposition="completed")
        gone = self.store.create_item("vanished", "d")
        for i in (open_item, closed_item, gone):
            self.store.link_goal_item(self.gid, i)
        del self.store._records[gone]

        text = assemble_goal_context(self.store, self.gid)

        opened, done = text.split("## Done items")
        self.assertIn("%s - still to do" % open_item, opened)
        self.assertIn("%s - finished" % closed_item, done)
        self.assertIn(gone, done)
        self.assertNotIn("%s -" % gone, done)
        for i in (open_item, closed_item, gone):
            self.assertEqual(text.count(i), 1)


class TestRefresh(_Base):
    def test_mints_one_labelled_item_with_one_agent_step_and_sets_the_pointer(self):
        step = self.uc.execute(self.gid)

        node = self.store.get_node(step)
        self.assertEqual((node.stage, node.role), (GOAL_STATE_OF_PLAY_STEP, "agent"))
        self.assertIn(SUMMARY_ORIGIN_LABEL, self.store.labels_of(node.item))
        item = self.store.get_node(node.item)
        self.assertTrue(item.id.startswith("SUM-"))
        self.assertEqual(item.title, "State of play: %s" % self.gid)
        self.assertEqual(item.description, assemble_goal_context(self.store, self.gid))
        self.assertEqual(self.store.goal_state_of_play_step(self.gid), step)
        self.assertEqual(self.store.goal_items(self.gid), [])

    def test_a_second_refresh_is_refused_naming_the_step_until_it_completes(self):
        step = self.uc.execute(self.gid)

        with self.assertRaises(UseCaseError) as ctx:
            self.uc.execute(self.gid)
        self.assertIn(step, str(ctx.exception))

        _attach_summary(self.store, step, "text")
        _complete(self.store, step)
        self.assertTrue(self.uc.execute(self.gid))

    def test_a_parked_step_still_blocks_but_a_deleted_one_does_not(self):
        step = self.uc.execute(self.gid)
        self.store.update_state(step, State.WAITING)
        with self.assertRaises(UseCaseError):
            self.uc.execute(self.gid)

        del self.store._records[step]
        self.assertTrue(self.uc.execute(self.gid))

    def test_refuses_a_goal_with_nothing_to_summarise_and_an_unknown_goal(self):
        empty = self.store.create_goal("empty")
        with self.assertRaises(UseCaseError):
            self.uc.execute(empty)
        with self.assertRaises(UseCaseError):
            self.uc.execute("G-99")


class TestCompletion(_Base):
    def test_write_then_read_through_the_attach_path_and_complete(self):
        before = self.snapshot()
        step = self.uc.execute(self.gid)
        _attach_summary(self.store, step, "do LC-861 first")

        _complete(self.store, step)

        goal = self.store.get_goal(self.gid)
        self.assertEqual(goal.state_of_play, "do LC-861 first")
        self.assertTrue(goal.state_of_play_at)
        self.assertIsNone(self.store.goal_state_of_play_step(self.gid))
        self.assertEqual(self.snapshot(), before)

    def test_the_closed_refresh_item_does_not_count_as_work(self):
        import datetime
        step = self.uc.execute(self.gid)
        _attach_summary(self.store, step, "text")
        _complete(self.store, step)

        self.assertEqual(self.store.get_node(self.store.get_node(step).item).state, State.DONE)
        self.assertEqual(closed_count(self.store, datetime.date.today()), 0)

    def test_a_non_done_outcome_releases_and_keeps_the_existing_text(self):
        first = self.uc.execute(self.gid)
        _attach_summary(self.store, first, "old")
        _complete(self.store, first)
        second = self.uc.execute(self.gid)
        _attach_summary(self.store, second, "new")

        _complete(self.store, second, outcome="failed")

        self.assertEqual(self.store.get_goal(self.gid).state_of_play, "old")
        self.assertIsNone(self.store.goal_state_of_play_step(self.gid))

    def test_a_missing_or_blank_summary_releases_and_keeps_the_existing_text(self):
        first = self.uc.execute(self.gid)
        _attach_summary(self.store, first, "old")
        _complete(self.store, first)
        for blank in (None, "   "):
            step = self.uc.execute(self.gid)
            if blank:
                _attach_summary(self.store, step, blank)

            _complete(self.store, step)

            self.assertEqual(self.store.get_goal(self.gid).state_of_play, "old")
            self.assertIsNone(self.store.goal_state_of_play_step(self.gid))

    def test_a_second_successful_refresh_replaces_the_first_text(self):
        for text in ("one", "two"):
            step = self.uc.execute(self.gid)
            _attach_summary(self.store, step, text)
            _complete(self.store, step)

        self.assertEqual(self.store.get_goal(self.gid).state_of_play, "two")

    def test_editing_the_goal_keeps_the_state_of_play_and_finishing_keeps_the_description(self):
        step = self.uc.execute(self.gid)
        _attach_summary(self.store, step, "text")
        _complete(self.store, step)

        self.store.update_goal(self.gid, description="rewritten")

        goal = self.store.get_goal(self.gid)
        self.assertEqual((goal.description, goal.state_of_play), ("rewritten", "text"))


class TestCli(_Base):
    def setUp(self):
        super().setUp()
        self._orig = cli._container
        self.addCleanup(lambda: cli.set_container(self._orig))
        cli.set_container(SimpleNamespace(store=self.store, config=FakeConfig()))

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.cmd_goal(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_refresh_queues_one_step_and_names_it(self):
        rc, out, _ = self._run("refresh", self.gid)

        step = self.store.goal_state_of_play_step(self.gid)
        self.assertEqual(rc, 0)
        self.assertEqual(
            out.strip(),
            "queued state of play for %s (%s); the pool writes it - read it with lc goal show %s"
            % (self.gid, step, self.gid),
        )
        self.assertEqual(len(self.store.steps_at_step(GOAL_STATE_OF_PLAY_STEP)), 1)

    def test_refresh_refusals_exit_one_with_a_message(self):
        self._run("refresh", self.gid)
        for argv in (("refresh", self.gid), ("refresh", "G-99")):
            rc, _, err = self._run(*argv)
            self.assertEqual(rc, 1)
            self.assertTrue(err.strip())

    def test_show_prints_the_block_after_the_description_only_when_present(self):
        _, before, _ = self._run("show", self.gid)
        self.assertNotIn("State of play", before)

        step = self.uc.execute(self.gid)
        _attach_summary(self.store, step, "do the thing first")
        _complete(self.store, step)
        _, after, _ = self._run("show", self.gid)

        self.assertLess(after.index("the problem"), after.index("State of play"))
        self.assertLess(after.index("State of play"), after.index("items:"))
        self.assertIn("do the thing first", after)


class TestPrompt(unittest.TestCase):
    def test_the_prompt_declares_a_model_and_invokes_only_worker_verbs(self):
        with open(PROMPT) as f:
            text = f.read()

        self.assertTrue(text.startswith("---\nmodel: "))
        verbs = {call["verb"] for call in lc_calls(text)}
        self.assertEqual(verbs, {"claim", "attach", "done"})
        self.assertLessEqual(verbs, set(WORKER_VERBS))
