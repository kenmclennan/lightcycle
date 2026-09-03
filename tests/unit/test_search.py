import io
import unittest
from contextlib import redirect_stdout

from lightcycle import cli
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
        s.close(tid, "done")
        resp = SearchUseCase(s).execute(SearchInput(text="pytest-bdd step"))
        self.assertEqual([m.node.id for m in resp.matches], [tid])
        self.assertEqual(resp.matches[0].node.state, State.DONE)

    def test_matches_an_in_progress_item(self):
        s = FakeStore()
        tid = s.create_item("pytest-bdd step precedence", "a description")
        s.update_state(tid, State.IN_PROGRESS)
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

    def test_step_nodes_are_excluded(self):
        s = FakeStore()
        item = s.create_item("an unrelated item", "an unrelated description")
        s.create_step("gh pr checks --json rejects conclusion", role="human", parent=item)
        resp = SearchUseCase(s).execute(SearchInput(text="gh pr checks"))
        self.assertEqual(resp.matches, [])


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


if __name__ == "__main__":
    unittest.main()
