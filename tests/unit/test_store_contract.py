"""Full port-contract suite against FakeStore (no subprocess)."""
import unittest

from tests.support.fake_store import FakeStore
from tests.support.store_contract import StoreContractBase


class TestFakeStoreContract(StoreContractBase, unittest.TestCase):

    def make_store(self):
        return FakeStore()

    def test_label_add_idempotent(self):
        s = self.make_store()
        tid = s.create_task("t", role="coder")
        s.label_add(tid, "for:coder")
        s.label_add(tid, "for:coder")
        self.assertEqual(s._beads[tid]["labels"].count("for:coder"), 1)

    def test_assign_clear_returns_to_ready(self):
        s = self.make_store()
        tid = s.create_task("t", role="coder")
        s.assign(tid, "worker-1")
        s.assign(tid, "")
        self.assertEqual(s.get_task(tid).status, "ready")

    def test_two_deps_require_both_closed(self):
        s = self.make_store()
        dep1 = s.create_task("dep1", role="coder")
        dep2 = s.create_task("dep2", role="coder")
        blocked = s.create_task("blocked", role="coder")
        s.dep_add(blocked, dep1)
        s.dep_add(blocked, dep2)
        s.close(dep1, "done")
        ready_ids = [b["id"] for b in s.ready_beads()]
        self.assertNotIn(blocked, ready_ids)
        s.close(dep2, "done")
        ready_ids = [b["id"] for b in s.ready_beads()]
        self.assertIn(blocked, ready_ids)

    def test_closed_task_not_in_ready(self):
        s = self.make_store()
        tid = s.create_task("t", role="coder")
        s.close(tid, "done")
        self.assertEqual(s.ready_beads(), [])

    def test_claimed_task_not_in_ready(self):
        s = self.make_store()
        tid = s.create_task("t", role="coder")
        s.assign(tid, "worker-1")
        self.assertEqual(s.ready_beads(), [])

    def test_stories_excluded_from_ready(self):
        s = self.make_store()
        s.create_story("story: foo")
        self.assertEqual(s.ready_beads(), [])

    def test_children_returns_child_beads(self):
        s = self.make_store()
        sid = s.create_story("story: foo")
        tid = s.create_task("task: t", parent=sid)
        kids = s.children(sid)
        self.assertEqual(len(kids), 1)
        self.assertEqual(kids[0].id, tid)

    def test_task_view_inherits_story_artifacts(self):
        s = self.make_store()
        sid = s.create_story("story: foo")
        tid = s.create_task("task: t", parent=sid)
        s.add_artifact(sid, "branch", "feat/foo")
        view = s.task_view(tid)
        self.assertTrue(any(a["type"] == "branch" for a in view["story_artifacts"]))

    def test_list_beads_by_status(self):
        s = self.make_store()
        open_tid = s.create_task("open")
        closed_tid = s.create_task("closed")
        s.close(closed_tid, "done")
        open_ids = [b["id"] for b in s.list_beads_by_status("open")]
        closed_ids = [b["id"] for b in s.list_beads_by_status("closed")]
        self.assertIn(open_tid, open_ids)
        self.assertNotIn(closed_tid, open_ids)
        self.assertIn(closed_tid, closed_ids)

    def test_closed_stories_roundtrip(self):
        s = self.make_store()
        sid = s.create_story("story: foo")
        s.add_artifact(sid, "spec", "specs/foo.md")
        s.close(sid, "done")
        stories = s.closed_stories()
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["id"], sid)
        self.assertEqual(stories[0]["outcome"], "done")
        self.assertEqual(len(stories[0]["artifacts"]), 1)

    def test_route_to_human(self):
        s = self.make_store()
        tid = s.create_task("t", step="build", role="coder")
        s.route_to_human(tid, "needs review", "coder")
        task = s.get_task(tid)
        self.assertEqual(task.role, "human")
        self.assertIn("needs review", task.notes)


if __name__ == "__main__":
    unittest.main()
