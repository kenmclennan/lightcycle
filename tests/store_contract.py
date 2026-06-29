"""StorePort contract: parameterised assertions shared by FakeStore and BdStore tests.

Subclass StoreContractBase together with unittest.TestCase and implement make_store()
to run the full suite against any StorePort implementation.
"""


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
        ready_ids = [b["id"] for b in s.ready_beads()]
        self.assertIn(tid, ready_ids)

    def test_task_with_unresolved_dep_not_ready(self):
        s = self.make_store()
        blocker = s.create_task("blocker", role="coder")
        blocked = s.create_task("blocked", role="coder")
        s.dep_add(blocked, blocker)
        ready_ids = [b["id"] for b in s.ready_beads()]
        self.assertNotIn(blocked, ready_ids)

    def test_all_deps_closed_makes_task_ready(self):
        s = self.make_store()
        blocker = s.create_task("blocker", role="coder")
        blocked = s.create_task("blocked", role="coder")
        s.dep_add(blocked, blocker)
        s.close(blocker, "done")
        ready_ids = [b["id"] for b in s.ready_beads()]
        self.assertIn(blocked, ready_ids)

    def test_claim_ready_matches_role_label(self):
        s = self.make_store()
        tid = s.create_task("t", role="coder")
        result = s.claim_ready("coder")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], tid)

    def test_claim_ready_wrong_role_returns_empty(self):
        s = self.make_store()
        s.create_task("t", role="coder")
        self.assertEqual(s.claim_ready("reviewer"), [])

    def test_story_artifacts_roundtrip(self):
        s = self.make_store()
        sid = s.create_story("story: foo")
        s.add_artifact(sid, "spec", "specs/foo.md")
        arts = s.story_artifacts(sid)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0]["type"], "spec")
        self.assertEqual(arts[0]["value"], "specs/foo.md")
