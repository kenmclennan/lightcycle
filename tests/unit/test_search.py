import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lightcycle import cli
from lightcycle.application.errors import UseCaseError
from lightcycle.application.work import SearchInput, SearchUseCase
from lightcycle.domain.work import State
from lightcycle.render import render_search
from tests.support.fake_store import FakeStore


class TestSearchUseCase(unittest.TestCase):
    def test_matches_a_phrase_only_present_in_the_description(self):
        s = FakeStore()
        tid = s.create_item("Four step-prompt fixes", "a description", project="lightcycle-workflows")
        s.edit_node(tid, description="gh pr checks --json rejects 'conclusion' on old runs")
        resp = SearchUseCase(s).execute(SearchInput(text="gh pr checks"))
        self.assertEqual([m.node.id for m in resp.matches], [tid])
        self.assertEqual(resp.matches[0].field, "description")

    def test_matches_a_done_item(self):
        s = FakeStore()
        tid = s.create_item("guard pytest-bdd step definitions", "a description")
        s.complete_node(tid, "done")
        resp = SearchUseCase(s).execute(SearchInput(text="pytest-bdd step"))
        self.assertEqual([m.node.id for m in resp.matches], [tid])
        self.assertEqual(resp.matches[0].node.state, State.DONE)

    def test_matches_an_in_progress_item(self):
        s = FakeStore()
        tid = s.create_item("pytest-bdd step precedence", "a description")
        s.update_state(tid, State.RUNNING)
        resp = SearchUseCase(s).execute(SearchInput(text="pytest-bdd step"))
        self.assertEqual([m.node.id for m in resp.matches], [tid])

    def test_no_match_returns_empty(self):
        s = FakeStore()
        s.create_item("something unrelated", "a description")
        resp = SearchUseCase(s).execute(SearchInput(text="nowhere to be found"))
        self.assertEqual(resp.matches, [])

    def test_match_is_case_insensitive(self):
        s = FakeStore()
        tid = s.create_item("Some Title With MixedCase", "a description")
        resp = SearchUseCase(s).execute(SearchInput(text="mixedcase"))
        self.assertEqual([m.node.id for m in resp.matches], [tid])

    def test_orders_a_two_digit_suffix_after_a_one_digit_suffix(self):
        s = FakeStore()
        s.create_item("ten", "pytest-bdd step", id="proj-10")
        s.create_item("nine", "pytest-bdd step", id="proj-9")
        resp = SearchUseCase(s).execute(SearchInput(text="pytest-bdd step"))
        self.assertEqual([m.node.id for m in resp.matches], ["proj-9", "proj-10"])

    def test_step_nodes_are_excluded(self):
        s = FakeStore()
        item = s.create_item("an unrelated item", "an unrelated description")
        s.create_step(role="human", parent=item)
        resp = SearchUseCase(s).execute(SearchInput(text="gh pr checks"))
        self.assertEqual(resp.matches, [])

    def test_match_repo_is_populated_independent_of_project(self):
        s = FakeStore()
        tid = s.create_item("pytest-bdd step precedence", "a description", project="proj-a")
        s.add_artifact(tid, "repo", "org/repo-a")
        resp = SearchUseCase(s).execute(SearchInput(text="pytest-bdd step"))
        self.assertEqual(resp.matches[0].repo, "org/repo-a")
        self.assertEqual(resp.matches[0].project, "proj-a")

    def test_terms_need_not_be_adjacent(self):
        s = FakeStore()
        tid = s.create_item("Step 5 teaches arithmetic the engine will do for you", "a description")
        resp = SearchUseCase(s).execute(SearchInput(text="arithmetic engine"))
        self.assertEqual([m.node.id for m in resp.matches], [tid])

    def test_terms_may_be_satisfied_by_different_fields(self):
        s = FakeStore()
        tid = s.create_item("arithmetic lesson", "the engine does it")
        resp = SearchUseCase(s).execute(SearchInput(text="arithmetic engine"))
        self.assertEqual([m.node.id for m in resp.matches], [tid])

    def test_term_order_does_not_matter(self):
        s = FakeStore()
        tid = s.create_item("teaches arithmetic the engine", "a description")
        resp = SearchUseCase(s).execute(SearchInput(text="engine arithmetic"))
        self.assertEqual([m.node.id for m in resp.matches], [tid])

    def test_row_missing_a_term_is_excluded(self):
        s = FakeStore()
        tid = s.create_item("Arithmetic ENGINE", "a description")
        s.create_item("arithmetic only", "a description")
        resp = SearchUseCase(s).execute(SearchInput(text="arithmetic engine"))
        self.assertEqual([m.node.id for m in resp.matches], [tid])

    def test_snippet_on_term_path_is_centred_on_first_term(self):
        s = FakeStore()
        tid = s.create_item("a title", "a description")
        s.edit_node(tid, description="x" * 80 + " engine " + "y" * 80 + " arithmetic " + "z" * 80)
        resp = SearchUseCase(s).execute(SearchInput(text="engine arithmetic"))
        self.assertEqual(resp.matches[0].field, "description")
        self.assertIn("engine", resp.matches[0].snippet)

    def test_none_description_and_notes_are_tolerated(self):
        s = FakeStore()
        tid = s.create_item("alpha beta", None)
        resp = SearchUseCase(s).execute(SearchInput(text="ALPHA beta"))
        self.assertEqual([m.node.id for m in resp.matches], [tid])

    def test_empty_and_whitespace_queries_raise(self):
        for text in ("", "   "):
            with self.assertRaises(UseCaseError):
                SearchUseCase(FakeStore()).execute(SearchInput(text=text))


class TestRenderSearch(unittest.TestCase):
    def test_line_contains_id_state_and_snippet(self):
        s = FakeStore()
        tid = s.create_item("a title", "a description")
        s.edit_node(tid, description="the matching phrase is here")
        resp = SearchUseCase(s).execute(SearchInput(text="matching phrase"))
        lines = render_search(resp.matches, 60)
        self.assertEqual(len(lines), 1)
        self.assertIn(tid, lines[0])
        self.assertIn("matching phrase", lines[0])


class FakeConfig:
    def max_title_length(self):
        return 72


class FakeContainer:
    def __init__(self, store):
        self.store = store
        self.config = FakeConfig()


class TestCmdSearch(unittest.TestCase):
    def test_parses_text_and_prints_matched_id(self):
        store = FakeStore()
        tid = store.create_item("an item", "a description")
        store.edit_node(tid, description="gh pr checks --json rejects 'conclusion'")
        cli.set_container(FakeContainer(store))
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.cmd_search(["gh pr checks"]) or 0
        self.assertEqual(rc, 0)
        self.assertIn(tid, out.getvalue())

    def test_empty_query_exits_one_with_message_on_stderr(self):
        cli.set_container(FakeContainer(FakeStore()))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.cmd_search([""])
        self.assertEqual(rc, 1)
        self.assertIn("at least one term", err.getvalue())
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
