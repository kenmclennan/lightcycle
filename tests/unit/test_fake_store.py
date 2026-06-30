"""Unit tests for FakeStore: bd semantic fidelity in isolation."""
import unittest

from tests.support.fake_store import FakeStore


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.s = FakeStore()
        self.tid = self.s.create_task("build: thing", step="build", role="coder")

    def test_step_and_role_split_into_separate_labels(self):
        task = self.s.get_task(self.tid)
        self.assertEqual(task.role, "coder")
        self.assertEqual(task.step, "build")

    def test_label_add_roundtrip(self):
        self.s.label_add(self.tid, "priority:high")
        raw = self.s._beads[self.tid]
        self.assertIn("priority:high", raw["labels"])

    def test_label_remove(self):
        self.s.label_add(self.tid, "tag:x")
        self.s.label_remove(self.tid, "tag:x")
        self.assertNotIn("tag:x", self.s._beads[self.tid]["labels"])

    def test_label_add_idempotent(self):
        self.s.label_add(self.tid, "tag:x")
        self.s.label_add(self.tid, "tag:x")
        self.assertEqual(self.s._beads[self.tid]["labels"].count("tag:x"), 1)

    def test_extra_labels_passed_to_create_task(self):
        tid = self.s.create_task("build: y", role="reviewer", labels=["project:foo"])
        task = self.s.get_task(tid)
        self.assertEqual(task.project, "foo")


class TestAssignee(unittest.TestCase):
    def setUp(self):
        self.s = FakeStore()
        self.tid = self.s.create_task("build: thing", role="coder")

    def test_assign_sets_in_progress(self):
        self.s.assign(self.tid, "worker-1")
        self.assertEqual(self.s.get_task(self.tid).status, "in-progress")

    def test_assign_empty_string_clears(self):
        self.s.assign(self.tid, "worker-1")
        self.s.assign(self.tid, "")
        self.assertEqual(self.s.get_task(self.tid).status, "ready")

    def test_assign_none_clears(self):
        self.s.assign(self.tid, "worker-1")
        self.s.assign(self.tid, None)
        self.assertIsNone(self.s._beads[self.tid]["assignee"])


class TestClose(unittest.TestCase):
    def setUp(self):
        self.s = FakeStore()
        self.tid = self.s.create_task("build: thing", role="coder")

    def test_close_sets_done_status(self):
        self.s.close(self.tid, "done")
        self.assertEqual(self.s.get_task(self.tid).status, "done")

    def test_close_reason_roundtrip(self):
        self.s.close(self.tid, "rejected")
        self.assertEqual(self.s.get_task(self.tid).outcome, "rejected")


class TestNotes(unittest.TestCase):
    def setUp(self):
        self.s = FakeStore()
        self.tid = self.s.create_task("build: thing")

    def test_note_absent_initially(self):
        self.assertIsNone(self.s.get_task(self.tid).notes)

    def test_note_roundtrip(self):
        self.s.note(self.tid, "from review (done): lgtm")
        self.assertEqual(self.s.get_task(self.tid).notes, "from review (done): lgtm")

    def test_multiple_notes_appended(self):
        self.s.note(self.tid, "first")
        self.s.note(self.tid, "second")
        notes = self.s.get_task(self.tid).notes
        self.assertIn("first", notes)
        self.assertIn("second", notes)


class TestParentChildren(unittest.TestCase):
    def setUp(self):
        self.s = FakeStore()
        self.story = self.s.create_story("story: foo")
        self.task = self.s.create_task("build: foo", parent=self.story)

    def test_child_has_parent(self):
        self.assertEqual(self.s.get_task(self.task).parent, self.story)

    def test_children_returns_child_bead(self):
        kids = self.s.children(self.story)
        self.assertEqual(len(kids), 1)
        self.assertEqual(kids[0].id, self.task)

    def test_children_excludes_other_beads(self):
        other_story = self.s.create_story("story: bar")
        self.s.create_task("build: bar", parent=other_story)
        self.assertEqual(len(self.s.children(self.story)), 1)

    def test_story_artifacts_roundtrip(self):
        self.s.add_artifact(self.story, "spec", "specs/foo.md")
        artifacts = self.s.story_artifacts(self.story)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].type, "spec")
        self.assertEqual(artifacts[0].value, "specs/foo.md")

    def test_add_artifact_with_label(self):
        self.s.add_artifact(self.story, "branch", "feat/foo", label="main branch")
        artifacts = self.s.story_artifacts(self.story)
        self.assertEqual(artifacts[0].label, "main branch")

    def test_task_view_inherits_story_artifacts(self):
        self.s.add_artifact(self.story, "branch", "feat/foo")
        view = self.s.task_view(self.task)
        self.assertTrue(any(a["type"] == "branch" for a in view["story_artifacts"]))

    def test_task_view_without_parent_uses_own_artifacts(self):
        orphan = self.s.create_task("build: orphan")
        view = self.s.task_view(orphan)
        self.assertEqual(view["story_artifacts"], [])


class TestReady(unittest.TestCase):
    def setUp(self):
        self.s = FakeStore()

    def test_task_without_deps_is_ready(self):
        tid = self.s.create_task("build: thing", role="coder")
        ready = self.s.ready_beads()
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["id"], tid)

    def test_task_with_open_dep_is_not_ready(self):
        blocker = self.s.create_task("build: dep", role="coder")
        blocked = self.s.create_task("build: thing", role="coder")
        self.s.dep_add(blocked, blocker)
        ready_ids = [b["id"] for b in self.s.ready_beads()]
        self.assertIn(blocker, ready_ids)
        self.assertNotIn(blocked, ready_ids)

    def test_closing_dep_makes_task_ready(self):
        blocker = self.s.create_task("build: dep", role="coder")
        blocked = self.s.create_task("build: thing", role="coder")
        self.s.dep_add(blocked, blocker)
        self.s.close(blocker, "done")
        ready_ids = [b["id"] for b in self.s.ready_beads()]
        self.assertIn(blocked, ready_ids)

    def test_task_with_two_deps_needs_both_closed(self):
        dep1 = self.s.create_task("build: dep1", role="coder")
        dep2 = self.s.create_task("build: dep2", role="coder")
        blocked = self.s.create_task("build: thing", role="coder")
        self.s.dep_add(blocked, dep1)
        self.s.dep_add(blocked, dep2)
        self.s.close(dep1, "done")
        ready_ids = [b["id"] for b in self.s.ready_beads()]
        self.assertNotIn(blocked, ready_ids)
        self.s.close(dep2, "done")
        ready_ids = [b["id"] for b in self.s.ready_beads()]
        self.assertIn(blocked, ready_ids)

    def test_claimed_task_not_in_ready(self):
        tid = self.s.create_task("build: thing", role="coder")
        self.s.assign(tid, "worker-1")
        self.assertEqual(self.s.ready_beads(), [])

    def test_closed_task_not_in_ready(self):
        tid = self.s.create_task("build: thing", role="coder")
        self.s.close(tid, "done")
        self.assertEqual(self.s.ready_beads(), [])

    def test_stories_excluded_from_ready(self):
        self.s.create_story("story: foo")
        self.assertEqual(self.s.ready_beads(), [])

    def test_claim_ready_assigns_and_returns(self):
        tid = self.s.create_task("build: thing", role="coder")
        result = self.s.claim_ready("coder")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], tid)
        self.assertTrue(result[0]["assignee"])

    def test_claim_ready_task_no_longer_in_ready(self):
        self.s.create_task("build: thing", role="coder")
        self.s.claim_ready("coder")
        self.assertEqual(self.s.ready_beads(), [])

    def test_claim_ready_wrong_role_returns_empty(self):
        self.s.create_task("build: thing", role="reviewer")
        self.assertEqual(self.s.claim_ready("coder"), [])

    def test_claim_ready_no_tasks_returns_empty(self):
        self.assertEqual(self.s.claim_ready("coder"), [])


class TestMetadata(unittest.TestCase):
    def setUp(self):
        self.s = FakeStore()
        self.tid = self.s.create_task("build: thing")

    def test_update_metadata_roundtrip(self):
        self.s.update_metadata(self.tid, {"needs": "a spec"})
        task = self.s.get_task(self.tid)
        self.assertEqual(task.needs, "a spec")

    def test_update_metadata_replaces(self):
        self.s.update_metadata(self.tid, {"needs": "old"})
        self.s.update_metadata(self.tid, {"artifacts": [{"type": "spec", "value": "s.md"}]})
        task = self.s.get_task(self.tid)
        self.assertIsNone(task.needs)
        self.assertEqual(len(task.artifacts), 1)


class TestListBeads(unittest.TestCase):
    def setUp(self):
        self.s = FakeStore()

    def test_list_by_status_open(self):
        t1 = self.s.create_task("build: a")
        t2 = self.s.create_task("build: b")
        self.s.close(t2, "done")
        open_ids = [b["id"] for b in self.s.list_beads_by_status("open")]
        self.assertIn(t1, open_ids)
        self.assertNotIn(t2, open_ids)

    def test_list_by_status_closed(self):
        t1 = self.s.create_task("build: a")
        t2 = self.s.create_task("build: b")
        self.s.close(t2, "done")
        closed_ids = [b["id"] for b in self.s.list_beads_by_status("closed")]
        self.assertIn(t2, closed_ids)
        self.assertNotIn(t1, closed_ids)

    def test_closed_stories_roundtrip(self):
        sid = self.s.create_story("story: foo")
        self.s.add_artifact(sid, "spec", "specs/foo.md")
        self.s.close(sid, "done")
        stories = self.s.closed_stories()
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["id"], sid)
        self.assertEqual(stories[0]["outcome"], "done")
        self.assertEqual(len(stories[0]["artifacts"]), 1)

    def test_closed_stories_excludes_tasks(self):
        tid = self.s.create_task("build: thing")
        self.s.close(tid, "done")
        self.assertEqual(self.s.closed_stories(), [])

    def test_closed_stories_excludes_open_stories(self):
        self.s.create_story("story: open")
        self.assertEqual(self.s.closed_stories(), [])


class TestRouteToHuman(unittest.TestCase):
    def setUp(self):
        self.s = FakeStore()
        self.tid = self.s.create_task("build: thing", step="build", role="coder")

    def test_routes_to_human(self):
        self.s.route_to_human(self.tid, "needs review", "coder")
        task = self.s.get_task(self.tid)
        self.assertEqual(task.role, "human")
        self.assertEqual(task.status, "needs-human")
        self.assertIsNone(self.s._beads[self.tid]["assignee"])

    def test_route_adds_note(self):
        self.s.route_to_human(self.tid, "needs review", "coder")
        self.assertIn("needs review", self.s.get_task(self.tid).notes)

    def test_route_removes_old_for_label(self):
        self.s.route_to_human(self.tid, "blocked", "coder")
        labels = self.s._beads[self.tid]["labels"]
        self.assertNotIn("for:coder", labels)
        self.assertIn("for:human", labels)


class TestNoSubprocess(unittest.TestCase):
    def test_importable_without_spawning_bd(self):
        from tests.support.fake_store import FakeStore as FS
        s = FS()
        tid = s.create_task("build: thing", role="coder")
        s.note(tid, "hello")
        s.close(tid, "done")


if __name__ == "__main__":
    unittest.main()
