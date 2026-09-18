import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

from lightcycle import cli
from lightcycle.application.errors import UseCaseError
from lightcycle.application.goals import (
    AppendGoalLogUseCase,
    AskGoalQuestionUseCase,
    CreateGoalInput,
    CreateGoalUseCase,
    EditGoalInput,
    EditGoalUseCase,
    LinkGoalItemUseCase,
    ListGoalsUseCase,
    ResolveGoalQuestionUseCase,
    ShowGoalUseCase,
    UnlinkGoalItemUseCase,
)
from lightcycle.domain.work.worker_permissions import worker_permitted
from tests.support.fake_store import FakeStore


class TestGoalUseCases(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.item = self.store.create_item("an item", "d")
        self.goal = CreateGoalUseCase(self.store).execute(CreateGoalInput(title="g"))

    def _snapshot(self):
        s = self.store
        return (
            s.list_goals(), s.goal_log(self.goal), s.goal_questions(self.goal),
            s.goal_items(self.goal),
        )

    def _refuses(self, fn, *args):
        before = self._snapshot()
        with self.assertRaises(UseCaseError):
            fn(*args)
        self.assertEqual(self._snapshot(), before)

    def test_write_then_read_across_every_part(self):
        s = self.store
        second = s.create_item("second item", "d")
        EditGoalUseCase(s).execute(EditGoalInput(
            id=self.goal, title="new title", outcome="the outcome", scope="the scope",
            status="in progress",
        ))
        AppendGoalLogUseCase(s).execute(self.goal, "decided x")
        q1 = AskGoalQuestionUseCase(s).execute(self.goal, "why?")
        AskGoalQuestionUseCase(s).execute(self.goal, "when?")
        ResolveGoalQuestionUseCase(s).execute(q1, "because")
        LinkGoalItemUseCase(s).execute(self.goal, self.item)
        LinkGoalItemUseCase(s).execute(self.goal, second)

        view = ShowGoalUseCase(s).execute(self.goal)

        self.assertEqual(
            (view.goal.title, view.goal.outcome, view.goal.scope, view.goal.status),
            ("new title", "the outcome", "the scope", "in progress"),
        )
        self.assertEqual(
            [e.body for e in view.log], ["Resolved: why? - because", "decided x"]
        )
        self.assertEqual([q.body for q in view.questions if q.resolved_at is None], ["when?"])
        self.assertEqual(
            [(r.id, r.title) for r in view.items],
            [(self.item, "an item"), (second, "second item")],
        )
        self.assertEqual([g.id for g in ListGoalsUseCase(s).execute()], [self.goal])

    def test_show_prints_bare_id_for_a_link_whose_item_is_gone(self):
        self.store._goal_items.append((self.goal, "LC-999"))
        view = ShowGoalUseCase(self.store).execute(self.goal)
        self.assertEqual([(r.id, r.title) for r in view.items], [("LC-999", None)])

    def test_show_resolves_all_and_none_of_the_linked_items(self):
        LinkGoalItemUseCase(self.store).execute(self.goal, self.item)
        self.assertEqual(ShowGoalUseCase(self.store).execute(self.goal).items[0].title, "an item")
        self.store._goal_items[:] = [(self.goal, "LC-998"), (self.goal, "LC-999")]
        view = ShowGoalUseCase(self.store).execute(self.goal)
        self.assertEqual([r.title for r in view.items], [None, None])

    def test_refuses_unknown_goal_everywhere(self):
        s = self.store
        for fn, args in (
            (ShowGoalUseCase(s).execute, ("G-9",)),
            (EditGoalUseCase(s).execute, (EditGoalInput(id="G-9", title="x"),)),
            (AppendGoalLogUseCase(s).execute, ("G-9", "x")),
            (AskGoalQuestionUseCase(s).execute, ("G-9", "x")),
            (LinkGoalItemUseCase(s).execute, ("G-9", self.item)),
            (UnlinkGoalItemUseCase(s).execute, ("G-9", self.item)),
        ):
            with self.assertRaises(UseCaseError):
                fn(*args)

    def test_refuses_unknown_question(self):
        self._refuses(ResolveGoalQuestionUseCase(self.store).execute, 42, "r")

    def test_refuses_invalid_status(self):
        self._refuses(
            EditGoalUseCase(self.store).execute, EditGoalInput(id=self.goal, status="blocked")
        )

    def test_refuses_empty_text(self):
        s = self.store
        self._refuses(CreateGoalUseCase(s).execute, CreateGoalInput(title="  "))
        self._refuses(AppendGoalLogUseCase(s).execute, self.goal, " ")
        self._refuses(AskGoalQuestionUseCase(s).execute, self.goal, "")
        q = AskGoalQuestionUseCase(s).execute(self.goal, "q?")
        self._refuses(ResolveGoalQuestionUseCase(s).execute, q, " ")

    def test_refuses_set_with_no_fields(self):
        self._refuses(EditGoalUseCase(self.store).execute, EditGoalInput(id=self.goal))

    def test_refuses_resolving_a_resolved_question(self):
        q = AskGoalQuestionUseCase(self.store).execute(self.goal, "q?")
        ResolveGoalQuestionUseCase(self.store).execute(q, "r")
        self._refuses(ResolveGoalQuestionUseCase(self.store).execute, q, "again")

    def test_refuses_linking_a_step_an_unknown_id_and_a_linked_pair(self):
        step = self.store.create_step(step="s", role="agent", parent=self.item)
        self._refuses(LinkGoalItemUseCase(self.store).execute, self.goal, step)
        self._refuses(LinkGoalItemUseCase(self.store).execute, self.goal, "LC-999")
        LinkGoalItemUseCase(self.store).execute(self.goal, self.item)
        self._refuses(LinkGoalItemUseCase(self.store).execute, self.goal, self.item)

    def test_refuses_unlinking_an_unlinked_pair(self):
        self._refuses(UnlinkGoalItemUseCase(self.store).execute, self.goal, self.item)

    def test_resolve_leaves_question_unresolved_when_the_log_write_fails(self):
        q = AskGoalQuestionUseCase(self.store).execute(self.goal, "q?")

        def boom(*a, **k):
            raise RuntimeError("log failed")

        self.store.add_goal_log = boom
        with self.assertRaises(RuntimeError):
            ResolveGoalQuestionUseCase(self.store).execute(q, "r")
        self.assertIsNone(self.store.get_goal_question(q).resolved_at)

    def test_goal_is_not_a_worker_verb(self):
        self.assertFalse(worker_permitted("goal", {}))


class TestGoalCli(unittest.TestCase):
    def setUp(self):
        self._orig = cli._container
        self.addCleanup(lambda: cli.set_container(self._orig))
        self.store = FakeStore()
        self.item = self.store.create_item("an item", "d")
        cli.set_container(SimpleNamespace(store=self.store))

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.cmd_goal(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_every_subcommand_happy_path(self):
        rc, out, _ = self._run("new", "Ship it", "--outcome", "o", "--scope", "s")
        self.assertEqual((rc, out.strip()), (0, "G-1"))
        self.assertEqual(self._run("set", "G-1", "--status", "in progress")[0], 0)
        self.assertEqual(self._run("log", "G-1", "decided")[0], 0)
        rc, out, _ = self._run("ask", "G-1", "why?")
        self.assertEqual((rc, out.strip()), (0, "#1"))
        self.assertEqual(self._run("link", "G-1", self.item)[0], 0)
        rc, out, _ = self._run("list")
        self.assertEqual(out.strip(), "G-1\tin progress\tShip it")
        _, out, _ = self._run("show", "G-1")
        for text in ("Ship it", "in progress", "o", "s", self.item, "an item", "#1", "decided"):
            self.assertIn(text, out)
        self.assertEqual(self._run("resolve", "1", "because")[0], 0)
        _, out, _ = self._run("show", "G-1")
        self.assertIn("Resolved: why? - because", out)
        self.assertEqual(self._run("unlink", "G-1", self.item)[0], 0)

    def test_refusals_exit_nonzero_with_a_message(self):
        self._run("new", "g")
        for argv in (
            ("show", "G-9"), ("set", "G-1"), ("set", "G-1", "--status", "x"),
            ("log", "G-1", ""), ("resolve", "7", "r"), ("link", "G-1", "LC-999"),
            ("unlink", "G-1", self.item),
        ):
            rc, _, err = self._run(*argv)
            self.assertEqual(rc, 1, argv)
            self.assertTrue(err.strip(), argv)
