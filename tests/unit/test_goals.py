import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

from lightcycle import cli
from lightcycle.application.errors import UseCaseError
from lightcycle.application.goals import (
    AppendGoalLogUseCase,
    log_entry_matches,
    CreateGoalInput,
    CreateGoalUseCase,
    EditGoalInput,
    EditGoalUseCase,
    LinkGoalItemUseCase,
    ListGoalsUseCase,
    ShowGoalUseCase,
    UnlinkGoalItemUseCase,
)
from lightcycle.domain.goals import GoalLogEntry, goal_log_stamp
from lightcycle.domain.work.worker_permissions import worker_permitted
from tests.support.fake_store import FakeStore


class TestGoalUseCases(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.item = self.store.create_item("an item", "d")
        self.goal = CreateGoalUseCase(self.store).execute(CreateGoalInput(title="g", project="acme"))

    def _snapshot(self):
        s = self.store
        return (
            s.list_goals(), s.goal_log(self.goal), s.goal_items(self.goal),
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
            id=self.goal, title="new title", description="the description",
            project="other", status="in progress",
        ))
        AppendGoalLogUseCase(s).execute(self.goal, "first", "decided x")
        AppendGoalLogUseCase(s).execute(self.goal, "second", "decided y")
        LinkGoalItemUseCase(s).execute(self.goal, self.item)
        LinkGoalItemUseCase(s).execute(self.goal, second)

        view = ShowGoalUseCase(s).execute(self.goal)

        self.assertEqual(
            (view.goal.title, view.goal.description, view.goal.project, view.goal.status),
            ("new title", "the description", "other", "in progress"),
        )
        self.assertEqual([e.title for e in view.log], ["second", "first"])
        self.assertEqual([e.body for e in view.log], ["decided y", "decided x"])
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
            (AppendGoalLogUseCase(s).execute, ("G-9", "t", "x")),
            (LinkGoalItemUseCase(s).execute, ("G-9", self.item)),
            (UnlinkGoalItemUseCase(s).execute, ("G-9", self.item)),
        ):
            with self.assertRaises(UseCaseError):
                fn(*args)

    def test_refuses_invalid_status(self):
        self._refuses(
            EditGoalUseCase(self.store).execute, EditGoalInput(id=self.goal, status="blocked")
        )

    def test_refuses_empty_text(self):
        s = self.store
        self._refuses(CreateGoalUseCase(s).execute, CreateGoalInput(title="  ", project="acme"))
        self._refuses(AppendGoalLogUseCase(s).execute, self.goal, "t", " ")
        self._refuses(AppendGoalLogUseCase(s).execute, self.goal, " ", "b")
        self._refuses(AppendGoalLogUseCase(s).execute, self.goal, "two\nlines", "b")
        self._refuses(CreateGoalUseCase(s).execute, CreateGoalInput(title="t", project=" "))
        self._refuses(CreateGoalUseCase(s).execute, CreateGoalInput(title="t"))
        self._refuses(
            EditGoalUseCase(s).execute, EditGoalInput(id=self.goal, project=" ")
        )

    def test_set_accepts_an_empty_description(self):
        EditGoalUseCase(self.store).execute(EditGoalInput(id=self.goal, description="x"))
        EditGoalUseCase(self.store).execute(EditGoalInput(id=self.goal, description=""))
        self.assertEqual(self.store.get_goal(self.goal).description, "")

    def test_refuses_set_with_no_fields(self):
        self._refuses(EditGoalUseCase(self.store).execute, EditGoalInput(id=self.goal))

    def test_refuses_linking_a_step_an_unknown_id_and_a_linked_pair(self):
        step = self.store.create_step(step="s", role="agent", parent=self.item)
        self._refuses(LinkGoalItemUseCase(self.store).execute, self.goal, step)
        self._refuses(LinkGoalItemUseCase(self.store).execute, self.goal, "LC-999")
        LinkGoalItemUseCase(self.store).execute(self.goal, self.item)
        self._refuses(LinkGoalItemUseCase(self.store).execute, self.goal, self.item)

    def test_refuses_unlinking_an_unlinked_pair(self):
        self._refuses(UnlinkGoalItemUseCase(self.store).execute, self.goal, self.item)

    def test_goal_is_not_a_worker_verb(self):
        self.assertFalse(worker_permitted("goal", {}))


class TestGoalCli(unittest.TestCase):
    def setUp(self):
        self._orig = cli._container
        self.addCleanup(lambda: cli.set_container(self._orig))
        self.store = FakeStore()
        self.store.add_project("acme/lightcycle")
        self.store.add_project("acme/saga")
        self.item = self.store.create_item("an item", "d")
        cli.set_container(SimpleNamespace(store=self.store))

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.cmd_goal(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_every_subcommand_happy_path(self):
        rc, out, _ = self._run(
            "new", "Ship it", "--project", "lightcycle", "--description", "the description"
        )
        self.assertEqual((rc, out.strip()), (0, "G-1"))
        self.assertEqual(self.store.get_goal("G-1").project, "lightcycle")
        self.assertEqual(self._run("set", "G-1", "--status", "in progress")[0], 0)
        self.assertEqual(self._run("set", "G-1", "--project", "saga")[0], 0)
        self.assertEqual(self.store.get_goal("G-1").project, "saga")
        self.assertEqual(self._run("log", "G-1", "a title", "decided")[0], 0)
        self.assertEqual(self._run("link", "G-1", self.item)[0], 0)
        rc, out, _ = self._run("list")
        self.assertEqual(out.strip(), "G-1\tin progress\tShip it")
        _, out, _ = self._run("show", "G-1")
        for text in (
            "Ship it", "saga", "in progress", "the description", self.item, "an item", "a title", "decided",
        ):
            self.assertIn(text, out)
        self.assertNotIn("open questions", out)
        self.assertEqual(self._run("unlink", "G-1", self.item)[0], 0)

    def test_set_accepts_an_empty_description(self):
        self._run("new", "g", "--project", "lightcycle", "--description", "x")
        self.assertEqual(self._run("set", "G-1", "--description", "")[0], 0)
        self.assertEqual(self.store.get_goal("G-1").description, "")

    def test_new_refuses_a_missing_or_unresolvable_project_leaving_the_store_untouched(self):
        for argv in (("new", "g"), ("new", "g", "--project", "nonesuch")):
            rc, _, err = self._run(*argv)
            self.assertEqual(rc, 1, argv)
            self.assertTrue(err.strip(), argv)
        self.assertEqual(self.store.list_goals(), [])

    def test_set_refuses_an_unresolvable_project(self):
        self._run("new", "g", "--project", "lightcycle")
        rc, _, err = self._run("set", "G-1", "--project", "nonesuch")
        self.assertEqual(rc, 1)
        self.assertTrue(err.strip())
        self.assertEqual(self.store.get_goal("G-1").project, "lightcycle")

    def test_refusals_exit_nonzero_with_a_message(self):
        self._run("new", "g", "--project", "lightcycle")
        for argv in (
            ("show", "G-9"), ("set", "G-1"), ("set", "G-1", "--status", "x"),
            ("log", "G-1", "", "b"), ("log", "G-1", "t", ""), ("log", "G-1", "a\nb", "b"), ("link", "G-1", "LC-999"), ("unlink", "G-1", self.item),
        ):
            rc, _, err = self._run(*argv)
            self.assertEqual(rc, 1, argv)
            self.assertTrue(err.strip(), argv)

    def test_log_requires_title_and_body_as_a_usage_error(self):
        self._run("new", "g", "--project", "lightcycle")
        for argv in (("log", "G-1", "only one"), ("log", "G-1")):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                cli.cmd_goal(list(argv))
            self.assertEqual(ctx.exception.code, 2, argv)
        self.assertEqual(self.store.goal_log("G-1"), [])

    def test_log_prints_confirmation(self):
        self._run("new", "g", "--project", "lightcycle")
        self.assertEqual(self._run("log", "G-1", "t", "b")[1].strip(), "logged to G-1")

    def test_show_prints_shortened_stamp_title_and_body_and_stamp_alone_when_untitled(self):
        self._run("new", "g", "--project", "lightcycle")
        self.store._now = lambda: "2026-09-19T09:30:12.123456+01:00"
        self._run("log", "G-1", "the title", "line one\nline two")
        self.store._goal_log.append(
            GoalLogEntry(99, "G-1", "", "no title body", "2026-09-19T10:00:00.000001+01:00")
        )
        _, out, _ = self._run("show", "G-1")
        self.assertIn("  2026-09-19 09:30  the title\n    line one\n    line two\n", out)
        self.assertIn("  2026-09-19 10:00\n    no title body", out)
        self.assertNotIn(":12", out)
        self.assertNotIn("123456", out)
        self.assertNotIn("+01:00", out)

    def test_removed_verbs_and_flags_are_rejected_by_the_parser(self):
        for argv in (
            ("ask", "G-1", "q"), ("resolve", "1", "r"),
            ("new", "g", "--project", "lightcycle", "--outcome", "o"),
            ("new", "g", "--project", "lightcycle", "--scope", "s"),
            ("set", "G-1", "--outcome", "o"), ("set", "G-1", "--scope", "s"),
        ):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.cmd_goal(list(argv))


class TestLogEntryMatches(unittest.TestCase):
    def _entry(self, title, body):
        return GoalLogEntry(1, "G-1", title, body, "2026-09-19T09:30:00+01:00")

    def test_matches_title_only_body_only_and_ignores_case(self):
        self.assertTrue(log_entry_matches(self._entry("Ratcheted Down", "b"), "ratcheted"))
        self.assertTrue(log_entry_matches(self._entry("t", "Starves the POOL"), "the pool"))
        self.assertFalse(log_entry_matches(self._entry("t", "b"), "zzz"))

    def test_empty_or_none_needle_matches_everything(self):
        entry = self._entry("t", "b")
        self.assertTrue(log_entry_matches(entry, ""))
        self.assertTrue(log_entry_matches(entry, None))

    def test_a_mixed_log_keeps_exactly_the_matching_entries_in_order(self):
        entries = [
            self._entry("alpha", "x"), self._entry("beta", "has alpha inside"),
            self._entry("gamma", "y"),
        ]
        self.assertEqual(
            [e.title for e in entries if log_entry_matches(e, "alpha")], ["alpha", "beta"]
        )
        self.assertEqual([e for e in entries if log_entry_matches(e, "nothing")], [])
        self.assertEqual(len([e for e in entries if log_entry_matches(e, "a")]), 3)


class TestGoalLogStamp(unittest.TestCase):
    def test_shortens_to_minutes_and_tolerates_missing(self):
        self.assertEqual(goal_log_stamp("2026-09-19T09:30:12.123456+01:00"), "2026-09-19 09:30")
        self.assertEqual(goal_log_stamp(None), "")
