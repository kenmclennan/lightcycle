class StoreContractBase:
    def make_store(self):
        raise NotImplementedError

    def test_label_add_visible_as_role(self):
        s = self.make_store()
        tid = s.create_task("t")
        s.label_add(tid, "for:reviewer")
        self.assertEqual(s.get_task(tid).role, "reviewer")

    def test_label_remove_clears_role(self):
        s = self.make_store()
        tid = s.create_task("t", role="coder")
        s.label_remove(tid, "for:coder")
        self.assertIsNone(s.get_task(tid).role)

    def test_assign_shows_in_progress(self):
        s = self.make_store()
        tid = s.create_task("t", role="coder")
        s.assign(tid, "worker-1")
        self.assertEqual(s.get_task(tid).status, "in-progress")

    def test_close_status_is_done(self):
        s = self.make_store()
        tid = s.create_task("t")
        s.close(tid, "done")
        self.assertEqual(s.get_task(tid).status, "done")

    def test_close_reason_preserved(self):
        s = self.make_store()
        tid = s.create_task("t")
        s.close(tid, "rejected")
        self.assertEqual(s.get_task(tid).outcome, "rejected")

    def test_close_overrides_in_progress(self):
        s = self.make_store()
        tid = s.create_task("t", role="coder")
        s.assign(tid, "worker-1")
        s.close(tid, "done")
        self.assertEqual(s.get_task(tid).status, "done")

    def test_note_roundtrip(self):
        s = self.make_store()
        tid = s.create_task("t")
        s.note(tid, "from review: lgtm")
        self.assertIn("from review: lgtm", s.get_task(tid).notes)

    def test_notes_append(self):
        s = self.make_store()
        tid = s.create_task("t")
        s.note(tid, "alpha")
        s.note(tid, "beta")
        notes = s.get_task(tid).notes
        self.assertIn("alpha", notes)
        self.assertIn("beta", notes)

    def test_task_without_deps_is_ready(self):
        s = self.make_store()
        tid = s.create_task("t", role="coder")
        ready_ids = [t.id for t in s.ready_tasks()]
        self.assertIn(tid, ready_ids)

    def test_task_with_unresolved_dep_not_ready(self):
        s = self.make_store()
        blocker = s.create_task("blocker", role="coder")
        blocked = s.create_task("blocked", role="coder")
        s.dep_add(blocked, blocker)
        ready_ids = [t.id for t in s.ready_tasks()]
        self.assertNotIn(blocked, ready_ids)

    def test_all_deps_closed_makes_task_ready(self):
        s = self.make_store()
        blocker = s.create_task("blocker", role="coder")
        blocked = s.create_task("blocked", role="coder")
        s.dep_add(blocked, blocker)
        s.close(blocker, "done")
        ready_ids = [t.id for t in s.ready_tasks()]
        self.assertIn(blocked, ready_ids)

    def test_claim_ready_matches_role_label(self):
        s = self.make_store()
        tid = s.create_task("t", role="coder")
        result = s.claim_ready("coder")
        self.assertEqual(result.id, tid)

    def test_claim_ready_wrong_role_returns_none(self):
        s = self.make_store()
        s.create_task("t", role="coder")
        self.assertIsNone(s.claim_ready("reviewer"))

    def test_story_artifacts_roundtrip(self):
        s = self.make_store()
        sid = s.create_story("story: foo")
        s.add_artifact(sid, "spec", "specs/foo.md")
        arts = s.story_artifacts(sid)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].type, "spec")
        self.assertEqual(arts[0].value, "specs/foo.md")

    def test_create_task_with_description(self):
        s = self.make_store()
        tid = s.create_task("my task", description="detailed info")
        t = s.get_task(tid)
        self.assertEqual(t.description, "detailed info")

    def test_edit_task_title_and_description(self):
        s = self.make_store()
        tid = s.create_task("old title", description="old desc")
        s.edit_task(tid, title="new title", description="new desc")
        t = s.get_task(tid)
        self.assertEqual(t.title, "new title")
        self.assertEqual(t.description, "new desc")

    def test_edit_task_goal_and_project(self):
        s = self.make_store()
        tid = s.create_task("t", goal="g1", project="p1")
        s.edit_task(tid, goal="g2", project="p2")
        t = s.get_task(tid)
        self.assertEqual(t.goal, "g2")
        self.assertEqual(t.project, "p2")

    def test_edit_task_leaves_unspecified_fields_intact(self):
        s = self.make_store()
        tid = s.create_task("title stays", description="desc stays", goal="g1")
        s.edit_task(tid, project="p1")
        t = s.get_task(tid)
        self.assertEqual(t.title, "title stays")
        self.assertEqual(t.description, "desc stays")
        self.assertEqual(t.goal, "g1")
        self.assertEqual(t.project, "p1")

    def test_edit_task_reparents(self):
        s = self.make_store()
        epic = s.create_story("epic")
        tid = s.create_task("a task")
        s.edit_task(tid, parent=epic)
        t = s.get_task(tid)
        self.assertEqual(t.parent, epic)

    def test_delete_removes_task(self):
        s = self.make_store()
        tid = s.create_task("t")
        s.delete(tid)
        self.assertNotIn(tid, [t.id for t in s.all_tasks()])

    def test_edit_task_parent_omitted_leaves_parent_unchanged(self):
        s = self.make_store()
        epic = s.create_story("epic")
        tid = s.create_task("a task", parent=epic)
        s.edit_task(tid, title="renamed")
        t = s.get_task(tid)
        self.assertEqual(t.parent, epic)

    def test_set_model_roundtrip(self):
        s = self.make_store()
        tid = s.create_task("t")
        s.set_model(tid, "sonnet")
        self.assertEqual(s.get_task(tid).model, "sonnet")

    def test_set_model_preserves_other_metadata(self):
        s = self.make_store()
        tid = s.create_task("t")
        s.update_metadata(tid, {"since": "2025-01-01"})
        s.set_model(tid, "sonnet")
        t = s.get_task(tid)
        self.assertEqual(t.model, "sonnet")
        self.assertEqual(t.since, "2025-01-01")

    def test_all_tasks_excludes_closed(self):
        s = self.make_store()
        open_tid = s.create_task("open task")
        closed_tid = s.create_task("closed task")
        s.close(closed_tid, "done")
        ids = [t.id for t in s.all_tasks()]
        self.assertIn(open_tid, ids)
        self.assertNotIn(closed_tid, ids)
