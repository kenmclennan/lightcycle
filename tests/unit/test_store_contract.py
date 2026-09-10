import os
import tempfile
import unittest

from lightcycle.config import Config
from tests.support.fake_store import FakeStore
from tests.support.store_contract import StoreContractBase
from tests.support.step_factory import create_owned_step


class TestFakeStoreContract(StoreContractBase, unittest.TestCase):
    def make_store(self, now=None):
        return FakeStore(now=now)

    def make_store_with_context_artifact_types(self, types):
        cfg_path = os.path.join(tempfile.mkdtemp(), "config")
        with open(cfg_path, "w") as f:
            f.write("context-artifact-types: %s\n" % " ".join(types))
        store = FakeStore()
        store.bind_config(Config(environ={"LC_CONFIG": cfg_path}))
        return store

    def test_unconfigured_default_kind_for_resolves_spec_to_filepath(self):
        s = FakeStore()
        self.assertEqual(s.default_kind_for("spec"), "filepath")

    def test_label_add_idempotent(self):
        s = self.make_store()
        tid = create_owned_step(s, "t", role="agent")
        s.label_add(tid, "for:coder")
        s.label_add(tid, "for:coder")
        self.assertEqual(s._records[tid]["labels"].count("for:coder"), 1)

    def test_assign_clear_returns_to_queued(self):
        s = self.make_store()
        tid = create_owned_step(s, "t", role="agent")
        s.assign(tid, "worker-1")
        s.assign(tid, "")
        self.assertEqual(s.get_node(tid).state, "queued")

    def test_two_deps_require_both_closed(self):
        s = self.make_store()
        dep1 = create_owned_step(s, "dep1", role="agent")
        dep2 = create_owned_step(s, "dep2", role="agent")
        blocked = create_owned_step(s, "blocked", role="agent")
        s.dep_add(blocked, dep1)
        s.dep_add(blocked, dep2)
        s.complete_node(dep1, "done")
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertNotIn(blocked, ready_ids)
        s.complete_node(dep2, "done")
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertIn(blocked, ready_ids)

    def test_closed_task_not_in_ready(self):
        s = self.make_store()
        tid = create_owned_step(s, "t", role="agent")
        s.complete_node(tid, "done")
        self.assertEqual(s.ready_steps(), [])

    def test_claimed_task_not_in_ready(self):
        s = self.make_store()
        tid = create_owned_step(s, "t", role="agent")
        s.assign(tid, "worker-1")
        self.assertEqual(s.ready_steps(), [])

    def test_stories_excluded_from_ready(self):
        s = self.make_store()
        s.create_item("item: foo", "a description")
        self.assertEqual(s.ready_steps(), [])

    def test_children_returns_child_records(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        tid = s.create_step("step: t", parent=sid)
        kids = s.children(sid)
        self.assertEqual(len(kids), 1)
        self.assertEqual(kids[0].id, tid)

    def test_task_view_inherits_story_artifacts(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        tid = s.create_step("step: t", parent=sid)
        s.add_artifact(sid, "branch", "feat/foo")
        view = s.node_view(tid)
        self.assertTrue(any(a.type == "branch" for a in view.item_artifacts))

    def test_claimed_tasks(self):
        s = self.make_store()
        claimed = create_owned_step(s, "t", role="agent")
        s.update_state(claimed, "in_progress")
        s.assign(claimed, "sp-x")
        ready = create_owned_step(s, "ready", role="agent")
        got = s.claimed_steps()
        self.assertEqual([t.id for t in got], [claimed])
        self.assertEqual(got[0].claimed_by, "sp-x")
        self.assertNotIn(ready, [t.id for t in got])

    def test_closed_stories_roundtrip(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "spec", "specs/foo.md")
        s.complete_node(sid, "done")
        items = s.closed_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], sid)
        self.assertEqual(items[0]["outcome"], "done")
        self.assertEqual(len(items[0]["artifacts"]), 1)

    def test_route_to_human(self):
        s = self.make_store()
        tid = create_owned_step(s, "t", step="build", role="agent")
        s.route_to_human(tid, "needs review")
        step = s.get_node(tid)
        self.assertEqual(step.role, "human")
        self.assertIn("needs review", step.notes)

    def test_disconnect_is_a_noop(self):
        s = self.make_store()
        s.release()
        create_owned_step(s, "t")


if __name__ == "__main__":
    unittest.main()
