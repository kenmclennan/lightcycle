import unittest

from lightcycle.application.work.item_context import ItemContextReader
from lightcycle.application.work.item_output_rows import ItemOutputRows
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_store import FakeStore


class TestItemContextReader(unittest.TestCase):
    def test_empty_item_has_no_context(self):
        s = FakeStore()
        item = s.create_item("item", "d")
        ctx = ItemContextReader(s).read(s.get_node(item))
        self.assertEqual((ctx.repo, ctx.workflow, ctx.goals, ctx.resolves, ctx.note), (None, None, (), (), None))

    def test_reads_repo_workflow_goal_and_resolves(self):
        s = FakeStore()
        backlog = s.create_item("Fix header", "d")
        item = s.create_item("item", "d", workflow="o/w@abc")
        s.add_artifact(item, "repo", "kenmclennan/lightcycle")
        s.add_artifact(item, "resolves", backlog, internal=True)
        s.add_artifact(item, "resolves", "LC-9999", internal=True)
        goal = s.create_goal("Ship the thing")
        s.link_goal_item(goal, item)
        other = s.create_goal("Unrelated")
        s.link_goal_item(other, backlog)
        ctx = ItemContextReader(s).read(s.get_node(item))
        self.assertEqual(ctx.repo, "kenmclennan/lightcycle")
        self.assertEqual(ctx.workflow, "o/w@abc")
        self.assertEqual(ctx.goals, ((goal, "Ship the thing"),))
        self.assertEqual(ctx.resolves, ((backlog, "Fix header"), ("LC-9999", None)))

    def test_note_shows_only_once_the_item_is_done(self):
        s = FakeStore()
        item = s.create_item("item", "d")
        s.complete_node(item, "merged", disposition="completed", note="shipped in #12")
        ctx = ItemContextReader(s).read(s.get_node(item))
        self.assertEqual(ctx.note, "shipped in #12")

    def test_note_is_hidden_while_the_item_is_not_done(self):
        s = FakeStore()
        item = s.create_item("item", "d")
        s._get(item)["note"] = "draft"
        self.assertIsNone(ItemContextReader(s).read(s.get_node(item)).note)


class TestItemOutputRows(unittest.TestCase):
    def test_rows_include_pr_rows_from_phase_runs(self):
        s = FakeStore()
        item = s.create_item("item", "d")
        pid = s.open_pass(item)
        run = s.open_run(item, pid, "code")
        s.set_pr(run, "https://gh/pr/5")
        flow = flow_from_metas({"w": {"model": "sonnet", "step": "build"}})
        rows = ItemOutputRows(s, flow).for_item(s.get_node(item))
        self.assertEqual([(r.name, r.label, r.value) for r in rows], [("pr", "code", "https://gh/pr/5")])


if __name__ == "__main__":
    unittest.main()
