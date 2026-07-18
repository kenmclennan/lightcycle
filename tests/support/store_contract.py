from lightcycle.domain.work import NodeSpec


class StoreContractBase:
    def make_store(self, now=None):
        raise NotImplementedError

    def test_complete_step_atomic_wins_and_files_successor(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        s.assign(tid, "w1")
        won, new = s.complete_step_atomic(
            tid, "done", "w1", NodeSpec(title="next", step="review", role="reviewer"))
        self.assertTrue(won)
        self.assertIsNotNone(new)
        self.assertEqual(s.get_node(tid).state, "done")
        self.assertEqual(s.get_node(tid).outcome, "done")

    def test_complete_step_atomic_already_done_loses(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        s.assign(tid, "w1")
        s.complete_step_atomic(tid, "done", "w1", None)
        won, new = s.complete_step_atomic(tid, "done", "w1", NodeSpec(title="next", step="review"))
        self.assertFalse(won)
        self.assertIsNone(new)

    def test_complete_step_atomic_fences_mismatched_assignee(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        s.assign(tid, "w1")
        won, new = s.complete_step_atomic(
            tid, "done", "w2", NodeSpec(title="next", step="review"))
        self.assertFalse(won)
        self.assertIsNone(new)
        self.assertEqual(s.get_node(tid).state, "in_progress")

    def test_complete_step_atomic_empty_assignee_not_fenced(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        s.assign(tid, "w1")
        won, _ = s.complete_step_atomic(tid, "done", "", None)
        self.assertTrue(won)
        self.assertEqual(s.get_node(tid).state, "done")

    def test_complete_step_atomic_worker_can_complete_an_unclaimed_step(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        won, new = s.complete_step_atomic(
            tid, "done", "handle-feedback-worker",
            NodeSpec(title="next", step="review", role="reviewer"))
        self.assertTrue(won)
        self.assertIsNotNone(new)
        self.assertEqual(s.get_node(tid).state, "done")

    def test_label_add_visible_as_role(self):
        s = self.make_store()
        tid = s.create_step("t")
        s.label_add(tid, "for:reviewer")
        self.assertEqual(s.get_node(tid).role, "reviewer")

    def test_label_remove_clears_role(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        s.label_remove(tid, "for:coder")
        self.assertIsNone(s.get_node(tid).role)

    def test_assign_shows_in_progress(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        s.assign(tid, "worker-1")
        self.assertEqual(s.get_node(tid).state, "in_progress")

    def test_close_status_is_done(self):
        s = self.make_store()
        tid = s.create_step("t")
        s.close(tid, "done")
        self.assertEqual(s.get_node(tid).state, "done")

    def test_outcome_preserved(self):
        s = self.make_store()
        tid = s.create_step("t")
        s.close(tid, "rejected")
        self.assertEqual(s.get_node(tid).outcome, "rejected")

    def test_close_overrides_in_progress(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        s.assign(tid, "worker-1")
        s.close(tid, "done")
        self.assertEqual(s.get_node(tid).state, "done")

    def test_note_roundtrip(self):
        s = self.make_store()
        tid = s.create_step("t")
        s.note(tid, "from review: lgtm")
        self.assertIn("from review: lgtm", s.get_node(tid).notes)

    def test_notes_append(self):
        s = self.make_store()
        tid = s.create_step("t")
        s.note(tid, "alpha")
        s.note(tid, "beta")
        notes = s.get_node(tid).notes
        self.assertIn("alpha", notes)
        self.assertIn("beta", notes)

    def test_set_notes_replaces_existing_notes(self):
        s = self.make_store()
        tid = s.create_step("t")
        s.note(tid, "alpha")
        s.set_notes(tid, "replacement")
        notes = s.get_node(tid).notes
        self.assertEqual(notes, "replacement")

    def test_set_notes_empty_clears_notes(self):
        s = self.make_store()
        tid = s.create_step("t")
        s.note(tid, "alpha")
        s.set_notes(tid, "")
        self.assertFalse(s.get_node(tid).notes)

    def test_task_without_deps_is_ready(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertIn(tid, ready_ids)

    def test_task_with_unresolved_dep_not_ready(self):
        s = self.make_store()
        blocker = s.create_step("blocker", role="coder")
        blocked = s.create_step("blocked", role="coder")
        s.dep_add(blocked, blocker)
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertNotIn(blocked, ready_ids)

    def test_all_deps_closed_makes_task_ready(self):
        s = self.make_store()
        blocker = s.create_step("blocker", role="coder")
        blocked = s.create_step("blocked", role="coder")
        s.dep_add(blocked, blocker)
        s.close(blocker, "done")
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertIn(blocked, ready_ids)

    def test_dep_remove_drops_blocker(self):
        s = self.make_store()
        blocker = s.create_step("blocker", role="coder")
        blocked = s.create_step("blocked", role="coder")
        s.dep_add(blocked, blocker)
        s.dep_remove(blocked, blocker)
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertIn(blocked, ready_ids)

    def test_dep_remove_of_absent_pair_removes_nothing(self):
        s = self.make_store()
        blocker = s.create_step("blocker", role="coder")
        blocked = s.create_step("blocked", role="coder")
        removed = s.dep_remove(blocked, blocker)
        self.assertFalse(removed)

    def test_dep_remove_returns_whether_a_dep_was_removed(self):
        s = self.make_store()
        blocker = s.create_step("blocker", role="coder")
        blocked = s.create_step("blocked", role="coder")
        s.dep_add(blocked, blocker)
        self.assertTrue(s.dep_remove(blocked, blocker))
        self.assertFalse(s.dep_remove(blocked, blocker))

    def test_dep_remove_leaves_unrelated_deps_untouched(self):
        s = self.make_store()
        blocker1 = s.create_step("blocker1", role="coder")
        blocker2 = s.create_step("blocker2", role="coder")
        blocked = s.create_step("blocked", role="coder")
        s.dep_add(blocked, blocker1)
        s.dep_add(blocked, blocker2)
        s.dep_remove(blocked, blocker1)
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertNotIn(blocked, ready_ids)
        s.close(blocker2, "done")
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertIn(blocked, ready_ids)

    def test_claim_ready_matches_role_label(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        result = s.claim_ready("coder")
        self.assertEqual(result.id, tid)

    def test_claim_ready_wrong_role_returns_none(self):
        s = self.make_store()
        s.create_step("t", role="coder")
        self.assertIsNone(s.claim_ready("reviewer"))

    def test_story_artifacts_roundtrip(self):
        s = self.make_store()
        sid = s.create_item("item: foo", theme=s.create_theme("theme"))
        s.add_artifact(sid, "spec", "specs/foo.md")
        arts = s.item_artifacts(sid)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].type, "spec")
        self.assertEqual(arts[0].value, "specs/foo.md")

    def test_add_artifact_still_appends_same_type(self):
        s = self.make_store()
        sid = s.create_item("item: foo", theme=s.create_theme("theme"))
        s.add_artifact(sid, "feedback", "first note")
        s.add_artifact(sid, "feedback", "second note")
        arts = [a for a in s.item_artifacts(sid) if a.type == "feedback"]
        self.assertEqual(len(arts), 2)

    def test_replace_artifact_replaces_existing_same_type(self):
        s = self.make_store()
        sid = s.create_item("item: foo", theme=s.create_theme("theme"))
        s.add_artifact(sid, "spec", "specs/old.md")
        s.replace_artifact(sid, "spec", "specs/new.md")
        arts = s.item_artifacts(sid)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].value, "specs/new.md")

    def test_replace_artifact_is_generic_for_any_type(self):
        s = self.make_store()
        sid = s.create_item("item: foo", theme=s.create_theme("theme"))
        s.add_artifact(sid, "repo", "app-old")
        s.replace_artifact(sid, "repo", "app-new")
        arts = [a for a in s.item_artifacts(sid) if a.type == "repo"]
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].value, "app-new")

    def test_create_epic_creates_epic_typed_task(self):
        s = self.make_store()
        eid = s.create_theme("objective")
        self.assertEqual(s.get_node(eid).type, "theme")

    def test_create_item_without_a_theme_is_an_untethered_todo(self):
        s = self.make_store()
        tid = s.create_item("item: foo")
        node = s.get_node(tid)
        self.assertIsNone(node.theme)
        self.assertEqual(node.state, "backlogged")

    def test_create_task_with_description(self):
        s = self.make_store()
        tid = s.create_step("my step", description="detailed info")
        t = s.get_node(tid)
        self.assertEqual(t.description, "detailed info")

    def test_edit_task_title_and_description(self):
        s = self.make_store()
        tid = s.create_step("old title", description="old desc")
        s.edit_node(tid, title="new title", description="new desc")
        t = s.get_node(tid)
        self.assertEqual(t.title, "new title")
        self.assertEqual(t.description, "new desc")

    def test_edit_task_goal_and_project(self):
        s = self.make_store()
        tid = s.create_step("t", goal="g1", project="p1")
        s.edit_node(tid, goal="g2", project="p2")
        t = s.get_node(tid)
        self.assertEqual(t.goal, "g2")
        self.assertEqual(t.project, "p2")

    def test_edit_task_leaves_unspecified_fields_intact(self):
        s = self.make_store()
        tid = s.create_step("title stays", description="desc stays", goal="g1")
        s.edit_node(tid, project="p1")
        t = s.get_node(tid)
        self.assertEqual(t.title, "title stays")
        self.assertEqual(t.description, "desc stays")
        self.assertEqual(t.goal, "g1")
        self.assertEqual(t.project, "p1")

    def test_edit_task_reparents(self):
        s = self.make_store()
        theme = s.create_item("theme", theme=s.create_theme("outer theme"))
        tid = s.create_step("a step")
        s.edit_node(tid, parent=theme)
        t = s.get_node(tid)
        self.assertEqual(t.parent, theme)

    def test_delete_removes_task(self):
        s = self.make_store()
        tid = s.create_step("t")
        s.delete(tid)
        self.assertNotIn(tid, [t.id for t in s.all_nodes()])

    def test_edit_task_parent_omitted_leaves_parent_unchanged(self):
        s = self.make_store()
        theme = s.create_item("theme", theme=s.create_theme("outer theme"))
        tid = s.create_step("a step", parent=theme)
        s.edit_node(tid, title="renamed")
        t = s.get_node(tid)
        self.assertEqual(t.parent, theme)

    def test_set_model_roundtrip(self):
        s = self.make_store()
        tid = s.create_step("t")
        s.set_model(tid, "sonnet")
        self.assertEqual(s.get_node(tid).model, "sonnet")

    def test_set_model_preserves_other_metadata(self):
        s = self.make_store()
        tid = s.create_step("t")
        s.update_metadata(tid, {"since": "2025-01-01"})
        s.set_model(tid, "sonnet")
        t = s.get_node(tid)
        self.assertEqual(t.model, "sonnet")
        self.assertEqual(t.since, "2025-01-01")

    def test_all_tasks_excludes_closed(self):
        s = self.make_store()
        open_tid = s.create_step("open step")
        closed_tid = s.create_step("closed step")
        s.close(closed_tid, "done")
        ids = [t.id for t in s.all_nodes()]
        self.assertIn(open_tid, ids)
        self.assertNotIn(closed_tid, ids)

    def test_history_records_claim_and_close_in_order(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        s.claim_ready("coder")
        s.close(tid, "done")
        states = [state for state, _ in s.history(tid)]
        self.assertEqual(states, ["in_progress", "done"])

    def test_history_stamps_ts_from_injected_clock(self):
        ticks = iter(["2026-01-01T10:00:00", "2026-01-01T10:30:00"])
        s = self.make_store(now=lambda: next(ticks))
        tid = s.create_step("t", role="coder")
        s.claim_ready("coder")
        s.close(tid, "done")
        self.assertEqual(
            [ts for _, ts in s.history(tid)],
            ["2026-01-01T10:00:00", "2026-01-01T10:30:00"],
        )

    def test_history_empty_for_unclaimed_task(self):
        s = self.make_store()
        tid = s.create_step("t", role="coder")
        self.assertEqual(s.history(tid), [])

    def test_all_steps_excludes_closed_steps(self):
        s = self.make_store()
        open_tid = s.create_step("open step")
        closed_tid = s.create_step("closed step")
        s.close(closed_tid, "done")
        ids = [t.id for t in s.all_steps()]
        self.assertIn(open_tid, ids)
        self.assertNotIn(closed_tid, ids)

    def test_all_steps_excludes_items_and_themes(self):
        s = self.make_store()
        theme = s.create_theme("theme")
        item = s.create_item("todo item", theme=theme)
        step = s.create_step("a step")
        ids = [t.id for t in s.all_steps()]
        self.assertEqual(ids, [step])
        self.assertNotIn(theme, ids)
        self.assertNotIn(item, ids)

    def test_step_state_backlogged_when_blocked(self):
        s = self.make_store()
        blocker = s.create_step("blocker")
        blocked = s.create_step("blocked", deps=[blocker])
        self.assertEqual(s.get_node(blocked).state, "backlogged")

    def test_step_state_in_progress_when_assigned_despite_deps(self):
        s = self.make_store()
        blocker = s.create_step("blocker")
        blocked = s.create_step("blocked", deps=[blocker])
        s.assign(blocked, "w1")
        self.assertEqual(s.get_node(blocked).state, "in_progress")

    def test_step_state_done_when_closed(self):
        s = self.make_store()
        blocker = s.create_step("blocker")
        blocked = s.create_step("blocked", deps=[blocker])
        s.assign(blocked, "w1")
        s.close(blocked, "done")
        self.assertEqual(s.get_node(blocked).state, "done")

    def test_step_state_ready_when_unblocked(self):
        s = self.make_store()
        blocker = s.create_step("blocker")
        blocked = s.create_step("blocked", deps=[blocker])
        s.close(blocker, "done")
        self.assertEqual(s.get_node(blocked).state, "ready")

    def test_item_state_rolls_up_mixed_children(self):
        s = self.make_store()
        item = s.create_item("item")
        done_step = s.create_step("done step", parent=item)
        s.create_step("open step", parent=item)
        s.close(done_step, "done")
        self.assertEqual(s.get_node(item).state, "in_progress")

    def test_item_state_done_when_all_children_done(self):
        s = self.make_store()
        item = s.create_item("item")
        a = s.create_step("a", parent=item)
        b = s.create_step("b", parent=item)
        s.close(a, "done")
        s.close(b, "done")
        self.assertEqual(s.get_node(item).state, "done")

    def test_item_state_ready_when_all_children_ready(self):
        s = self.make_store()
        item = s.create_item("item")
        s.create_step("a", parent=item)
        s.create_step("b", parent=item)
        self.assertEqual(s.get_node(item).state, "ready")

    def test_empty_item_state_backlogged(self):
        s = self.make_store()
        item = s.create_item("item")
        self.assertEqual(s.get_node(item).state, "backlogged")

    def test_step_state_ready_when_in_progress_column_but_unassigned(self):
        s = self.make_store()
        tid = s.create_step("t")
        s.update_state(tid, "in_progress")
        self.assertEqual(s.get_node(tid).state, "ready")

    def test_closed_empty_container_state_done(self):
        s = self.make_store()
        item = s.create_item("item")
        s.close(item, "done")
        self.assertEqual(s.get_node(item).state, "done")
