from lightcycle.domain.work import NodeSpec
from lightcycle.ports.store import NodeNotFoundError, ProjectResolutionError


class StoreContractBase:
    def _step(self, s, title="t", **kw):
        if kw.get("parent") is None:
            kw["parent"] = s.create_item("owner", "an owning item")
        return s.create_step(title, **kw)

    def make_store(self, now=None):
        raise NotImplementedError

    def test_complete_step_atomic_wins_and_files_successor(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.assign(tid, "w1")
        won, new = s.complete_step_atomic(
            tid, "done", "w1", NodeSpec(title="next", step="review", role="agent",
                     parent=s.get_step(tid).item))
        self.assertTrue(won)
        self.assertIsNotNone(new)
        self.assertEqual(s.get_node(tid).state, "done")
        self.assertEqual(s.get_node(tid).outcome, "done")

    def test_complete_step_atomic_already_done_loses(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.assign(tid, "w1")
        s.complete_step_atomic(tid, "done", "w1", None)
        won, new = s.complete_step_atomic(tid, "done", "w1", NodeSpec(title="next", step="review"))
        self.assertFalse(won)
        self.assertIsNone(new)

    def test_complete_step_atomic_fences_mismatched_assignee(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.assign(tid, "w1")
        won, new = s.complete_step_atomic(
            tid, "done", "w2", NodeSpec(title="next", step="review"))
        self.assertFalse(won)
        self.assertIsNone(new)
        self.assertEqual(s.get_node(tid).state, "in_progress")

    def test_complete_step_atomic_empty_assignee_not_fenced(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.assign(tid, "w1")
        won, _ = s.complete_step_atomic(tid, "done", "", None)
        self.assertTrue(won)
        self.assertEqual(s.get_node(tid).state, "done")

    def test_complete_step_atomic_worker_can_complete_an_unclaimed_step(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        won, new = s.complete_step_atomic(
            tid, "done", "handle-feedback-worker",
            NodeSpec(title="next", step="review", role="agent",
                     parent=s.get_step(tid).item))
        self.assertTrue(won)
        self.assertIsNotNone(new)
        self.assertEqual(s.get_node(tid).state, "done")

    def test_label_add_visible_as_role(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.label_add(tid, "for:reviewer")
        self.assertEqual(s.get_node(tid).role, "reviewer")

    def test_label_remove_clears_role(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.label_remove(tid, "for:agent")
        self.assertIsNone(s.get_node(tid).role)

    def test_labels_of_reflects_add_and_remove(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.label_add(tid, "ci-pending")
        s.label_add(tid, "ci-released:1")
        self.assertEqual(set(s.labels_of(tid)), {"ci-pending", "ci-released:1"})
        s.label_remove(tid, "ci-pending")
        self.assertEqual(set(s.labels_of(tid)), {"ci-released:1"})

    def test_assign_shows_in_progress(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.assign(tid, "worker-1")
        self.assertEqual(s.get_node(tid).state, "in_progress")

    def test_close_status_is_done(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.close(tid, "done")
        self.assertEqual(s.get_node(tid).state, "done")

    def test_outcome_preserved(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.close(tid, "rejected")
        self.assertEqual(s.get_node(tid).outcome, "rejected")

    def test_close_overrides_in_progress(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.assign(tid, "worker-1")
        s.close(tid, "done")
        self.assertEqual(s.get_node(tid).state, "done")

    def test_note_roundtrip(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.note(tid, "from review: lgtm")
        self.assertIn("from review: lgtm", s.get_node(tid).notes)

    def test_notes_append(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.note(tid, "alpha")
        s.note(tid, "beta")
        notes = s.get_node(tid).notes
        self.assertIn("alpha", notes)
        self.assertIn("beta", notes)

    def test_set_notes_replaces_existing_notes(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.note(tid, "alpha")
        s.set_notes(tid, "replacement")
        notes = s.get_node(tid).notes
        self.assertEqual(notes, "replacement")

    def test_set_notes_empty_clears_notes(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.note(tid, "alpha")
        s.set_notes(tid, "")
        self.assertFalse(s.get_node(tid).notes)

    def test_note_condition_repeated_collapses_to_one_growing_line(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.note_condition(tid, "gh read failed")
        once = s.get_node(tid).notes
        s.note_condition(tid, "gh read failed")
        twice = s.get_node(tid).notes
        self.assertEqual(len(twice.splitlines()), 1)
        self.assertNotEqual(once, twice)
        self.assertIn("x2", twice)

    def test_note_condition_different_text_appends_a_new_line(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.note_condition(tid, "condition A")
        s.note_condition(tid, "condition B")
        lines = s.get_node(tid).notes.splitlines()
        self.assertEqual(len(lines), 2)

    def test_note_condition_non_adjacent_recurrence_starts_a_fresh_line(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.note_condition(tid, "A")
        s.note_condition(tid, "B")
        s.note_condition(tid, "A")
        lines = s.get_node(tid).notes.splitlines()
        self.assertEqual(len(lines), 3)

    def test_note_condition_normalizes_embedded_newlines_and_still_dedupes(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.note_condition(tid, "line one\nline two")
        s.note_condition(tid, "line one\nline two")
        lines = s.get_node(tid).notes.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("x2", lines[0])

    def test_note_condition_does_not_upgrade_a_plain_note(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.note(tid, "X")
        s.note_condition(tid, "X")
        lines = s.get_node(tid).notes.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "X")

    def test_note_condition_unknown_node_raises_node_not_found(self):
        s = self.make_store()
        with self.assertRaises(NodeNotFoundError):
            s.note_condition("does-not-exist", "gh read failed")

    def test_task_without_deps_is_ready(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertIn(tid, ready_ids)

    def test_task_with_unresolved_dep_not_ready(self):
        s = self.make_store()
        blocker = self._step(s, "blocker", role="agent")
        blocked = self._step(s, "blocked", role="agent")
        s.dep_add(blocked, blocker)
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertNotIn(blocked, ready_ids)

    def test_all_deps_closed_makes_task_ready(self):
        s = self.make_store()
        blocker = self._step(s, "blocker", role="agent")
        blocked = self._step(s, "blocked", role="agent")
        s.dep_add(blocked, blocker)
        s.close(blocker, "done")
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertIn(blocked, ready_ids)

    def test_dep_remove_drops_blocker(self):
        s = self.make_store()
        blocker = self._step(s, "blocker", role="agent")
        blocked = self._step(s, "blocked", role="agent")
        s.dep_add(blocked, blocker)
        s.dep_remove(blocked, blocker)
        ready_ids = [t.id for t in s.ready_steps()]
        self.assertIn(blocked, ready_ids)

    def test_dep_remove_of_absent_pair_removes_nothing(self):
        s = self.make_store()
        blocker = self._step(s, "blocker", role="agent")
        blocked = self._step(s, "blocked", role="agent")
        removed = s.dep_remove(blocked, blocker)
        self.assertFalse(removed)

    def test_dep_remove_returns_whether_a_dep_was_removed(self):
        s = self.make_store()
        blocker = self._step(s, "blocker", role="agent")
        blocked = self._step(s, "blocked", role="agent")
        s.dep_add(blocked, blocker)
        self.assertTrue(s.dep_remove(blocked, blocker))
        self.assertFalse(s.dep_remove(blocked, blocker))

    def test_blocked_by_names_a_single_unresolved_dependency(self):
        s = self.make_store()
        dep1 = self._step(s, "dep1", role="agent")
        blocked = self._step(s, "blocked", role="agent")
        s.dep_add(blocked, dep1)
        node = s.get_node(blocked)
        self.assertEqual(set(node.blocked_by), {dep1})
        self.assertEqual(node.deps, 1)

    def test_blocked_by_names_every_unresolved_dependency_at_once(self):
        s = self.make_store()
        dep1 = self._step(s, "dep1", role="agent")
        dep2 = self._step(s, "dep2", role="agent")
        blocked = self._step(s, "blocked", role="agent")
        s.dep_add(blocked, dep1)
        s.dep_add(blocked, dep2)
        node = s.get_node(blocked)
        self.assertEqual(set(node.blocked_by), {dep1, dep2})
        self.assertEqual(node.deps, 2)

    def test_blocked_by_drops_only_the_dependency_that_closed(self):
        s = self.make_store()
        dep1 = self._step(s, "dep1", role="agent")
        dep2 = self._step(s, "dep2", role="agent")
        blocked = self._step(s, "blocked", role="agent")
        s.dep_add(blocked, dep1)
        s.dep_add(blocked, dep2)
        s.close(dep1, "done")
        node = s.get_node(blocked)
        self.assertEqual(set(node.blocked_by), {dep2})
        self.assertEqual(node.deps, 1)

    def test_blocked_by_drops_a_deleted_dependency(self):
        s = self.make_store()
        dep1 = self._step(s, "dep1", role="agent")
        blocked = self._step(s, "blocked", role="agent")
        s.dep_add(blocked, dep1)
        s.delete(dep1)
        node = s.get_node(blocked)
        self.assertEqual(node.blocked_by, [])
        self.assertEqual(node.deps, 0)

    def test_blocked_by_empty_when_no_dependencies(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        node = s.get_node(tid)
        self.assertEqual(node.blocked_by, [])
        self.assertEqual(node.deps, 0)

    def test_dep_remove_leaves_unrelated_deps_untouched(self):
        s = self.make_store()
        blocker1 = self._step(s, "blocker1", role="agent")
        blocker2 = self._step(s, "blocker2", role="agent")
        blocked = self._step(s, "blocked", role="agent")
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
        tid = self._step(s, "t", role="agent")
        result = s.claim_ready("agent")
        self.assertEqual(result.id, tid)

    def test_claim_ready_wrong_role_returns_none(self):
        s = self.make_store()
        self._step(s, "t", role="human")
        self.assertIsNone(s.claim_ready("agent"))

    def test_story_artifacts_roundtrip(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "spec", "specs/foo.md")
        arts = s.item_artifacts(sid)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].type, "spec")
        self.assertEqual(arts[0].value, "specs/foo.md")

    def test_add_artifact_still_appends_same_type(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "feedback", "first note")
        s.add_artifact(sid, "feedback", "second note")
        arts = [a for a in s.item_artifacts(sid) if a.type == "feedback"]
        self.assertEqual(len(arts), 2)

    def test_replace_artifact_replaces_existing_same_type(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "spec", "specs/old.md")
        s.replace_artifact(sid, "spec", "specs/new.md")
        arts = s.item_artifacts(sid)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].value, "specs/new.md")

    def test_replace_artifact_is_generic_for_any_type(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "spec", "app-old")
        s.replace_artifact(sid, "spec", "app-new")
        arts = [a for a in s.item_artifacts(sid) if a.type == "spec"]
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].value, "app-new")

    def test_add_artifact_declared_kind_overrides_type_default(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "pr", "https://gh/1", kind="text")
        arts = s.item_artifacts(sid)
        self.assertEqual(arts[0].kind, "text")

    def test_add_artifact_undeclared_kind_resolves_from_type_table(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "pr", "https://gh/1")
        s.add_artifact(sid, "spec", "specs/foo.md")
        s.add_artifact(sid, "branch", "feat/x")
        s.add_artifact(sid, "resolves", "OTHER-1")
        kinds = {a.type: a.kind for a in s.item_artifacts(sid)}
        self.assertEqual(kinds, {
            "pr": "url", "spec": "filepath",
            "branch": "text", "resolves": "text",
        })

    def test_add_artifact_internal_defaults_false_and_persists_true(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "pr", "https://gh/1")
        s.add_artifact(sid, "reflection", "{}", internal=True)
        arts = {a.type: a for a in s.item_artifacts(sid)}
        self.assertFalse(arts["pr"].internal)
        self.assertTrue(arts["reflection"].internal)

    def test_replace_artifact_applies_declared_and_default_kind_and_internal(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "pr", "https://gh/1")
        s.replace_artifact(sid, "pr", "https://gh/2", kind="text", internal=True)
        arts = [a for a in s.item_artifacts(sid) if a.type == "pr"]
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].kind, "text")
        self.assertTrue(arts[0].internal)

    def test_create_item_is_a_top_level_todo(self):
        s = self.make_store()
        tid = s.create_item("item: foo", "a description")
        node = s.get_node(tid)
        self.assertEqual(node.type, "item")
        self.assertIsNone(node.parent)
        self.assertEqual(node.state, "backlogged")

    def test_create_item_with_description(self):
        s = self.make_store()
        tid = s.create_item("my item", "detailed info")
        self.assertEqual(s.get_item(tid).description, "detailed info")

    def test_edit_item_title_and_description(self):
        s = self.make_store()
        tid = s.create_item("old title", "old desc")
        s.edit_node(tid, title="new title", description="new desc")
        t = s.get_item(tid)
        self.assertEqual(t.title, "new title")
        self.assertEqual(t.description, "new desc")

    def test_edit_item_leaves_unspecified_fields_intact(self):
        s = self.make_store()
        tid = s.create_item("title stays", "desc stays")
        s.edit_node(tid, project="p1")
        t = s.get_item(tid)
        self.assertEqual(t.title, "title stays")
        self.assertEqual(t.description, "desc stays")
        self.assertEqual(t.project, "p1")

    def test_a_step_carries_no_description(self):
        s = self.make_store()
        tid = self._step(s, "a step")
        self.assertFalse(hasattr(s.get_step(tid), "description"))

    def test_a_steps_item_is_fixed_at_creation(self):
        s = self.make_store()
        item = s.create_item("owning item", "a description")
        tid = self._step(s, "a step", parent=item)
        s.edit_node(tid, title="renamed")
        self.assertEqual(s.get_step(tid).item, item)

    def test_delete_removes_task(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.delete(tid)
        self.assertNotIn(tid, [t.id for t in s.all_nodes()])

    def test_edit_task_parent_omitted_leaves_parent_unchanged(self):
        s = self.make_store()
        item = s.create_item("owning item", "a description")
        tid = self._step(s, "a step", parent=item)
        s.edit_node(tid, title="renamed")
        t = s.get_node(tid)
        self.assertEqual(t.parent, item)

    def test_set_model_roundtrip(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.set_model(tid, "sonnet")
        self.assertEqual(s.get_node(tid).model, "sonnet")

    def test_set_model_preserves_other_metadata(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.set_model(tid, "sonnet")
        t = s.get_node(tid)
        self.assertEqual(t.model, "sonnet")

    def test_update_metadata_preserves_other_metadata(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.set_model(tid, "sonnet")
        t = s.get_node(tid)
        self.assertEqual(t.model, "sonnet")

    def test_update_metadata_persists_resume_fields(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.update_metadata(tid, {"reason": "oops", "tried": "a,b"})
        t = s.get_node(tid)
        self.assertEqual(t.park.reason, "oops")
        self.assertEqual(t.park.tried, "a,b")

    def test_all_tasks_excludes_closed(self):
        s = self.make_store()
        open_tid = self._step(s, "open step")
        closed_tid = self._step(s, "closed step")
        s.close(closed_tid, "done")
        ids = [t.id for t in s.all_nodes()]
        self.assertIn(open_tid, ids)
        self.assertNotIn(closed_tid, ids)

    def test_all_nodes_including_done_includes_closed_nodes(self):
        s = self.make_store()
        open_tid = self._step(s, "open step")
        closed_tid = self._step(s, "closed step")
        s.close(closed_tid, "done")
        ids = [t.id for t in s.all_nodes()]
        self.assertIn(open_tid, ids)
        self.assertNotIn(closed_tid, ids)
        all_ids = [t.id for t in s.all_nodes_including_done()]
        self.assertIn(open_tid, all_ids)
        self.assertIn(closed_tid, all_ids)

    def test_history_records_claim_and_close_in_order(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.claim_ready("agent")
        s.close(tid, "done")
        states = [state for state, _ in s.history(tid)]
        self.assertEqual(states, ["in_progress", "done"])

    def test_history_stamps_ts_from_injected_clock(self):
        ticks = iter(["2026-01-01T10:00:00", "2026-01-01T10:30:00"])
        s = self.make_store(now=lambda: next(ticks))
        tid = self._step(s, "t", role="agent")
        s.claim_ready("agent")
        s.close(tid, "done")
        self.assertEqual(
            [ts for _, ts in s.history(tid)],
            ["2026-01-01T10:00:00", "2026-01-01T10:30:00"],
        )

    def test_history_empty_for_unclaimed_task(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        self.assertEqual(s.history(tid), [])

    def test_all_steps_excludes_closed_steps(self):
        s = self.make_store()
        open_tid = self._step(s, "open step")
        closed_tid = self._step(s, "closed step")
        s.close(closed_tid, "done")
        ids = [t.id for t in s.all_steps()]
        self.assertIn(open_tid, ids)
        self.assertNotIn(closed_tid, ids)

    def test_all_steps_excludes_items(self):
        s = self.make_store()
        item = s.create_item("todo item", "a description")
        step = self._step(s, "a step")
        ids = [t.id for t in s.all_steps()]
        self.assertEqual(ids, [step])
        self.assertNotIn(item, ids)

    def test_step_state_backlogged_when_blocked(self):
        s = self.make_store()
        blocker = self._step(s, "blocker")
        blocked = self._step(s, "blocked", deps=[blocker])
        self.assertEqual(s.get_node(blocked).state, "backlogged")

    def test_step_state_in_progress_when_assigned_despite_deps(self):
        s = self.make_store()
        blocker = self._step(s, "blocker")
        blocked = self._step(s, "blocked", deps=[blocker])
        s.assign(blocked, "w1")
        self.assertEqual(s.get_node(blocked).state, "in_progress")

    def test_step_state_done_when_closed(self):
        s = self.make_store()
        blocker = self._step(s, "blocker")
        blocked = self._step(s, "blocked", deps=[blocker])
        s.assign(blocked, "w1")
        s.close(blocked, "done")
        self.assertEqual(s.get_node(blocked).state, "done")

    def test_step_state_ready_when_unblocked(self):
        s = self.make_store()
        blocker = self._step(s, "blocker")
        blocked = self._step(s, "blocked", deps=[blocker])
        s.close(blocker, "done")
        self.assertEqual(s.get_node(blocked).state, "ready")

    def test_step_state_ready_when_blocker_deleted(self):
        s = self.make_store()
        blocker = self._step(s, "blocker")
        blocked = self._step(s, "blocked", deps=[blocker])
        s.delete(blocker)
        self.assertEqual(s.get_node(blocked).state, "ready")

    def test_item_state_rolls_up_mixed_children(self):
        s = self.make_store()
        item = s.create_item("item", "a description")
        done_step = self._step(s, "done step", parent=item)
        self._step(s, "open step", parent=item)
        s.close(done_step, "done")
        self.assertEqual(s.get_node(item).state, "in_progress")

    def test_item_state_done_when_all_children_done(self):
        s = self.make_store()
        item = s.create_item("item", "a description")
        a = self._step(s, "a", parent=item)
        b = self._step(s, "b", parent=item)
        s.close(a, "done")
        s.close(b, "done")
        self.assertEqual(s.get_node(item).state, "done")

    def test_item_state_ready_when_all_children_ready(self):
        s = self.make_store()
        item = s.create_item("item", "a description")
        self._step(s, "a", parent=item)
        self._step(s, "b", parent=item)
        self.assertEqual(s.get_node(item).state, "ready")

    def test_empty_item_state_backlogged(self):
        s = self.make_store()
        item = s.create_item("item", "a description")
        self.assertEqual(s.get_node(item).state, "backlogged")

    def test_step_state_ready_when_in_progress_column_but_unassigned(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.update_state(tid, "in_progress")
        self.assertEqual(s.get_node(tid).state, "ready")

    def test_closed_empty_container_state_done(self):
        s = self.make_store()
        item = s.create_item("item", "a description")
        s.close(item, "done")
        self.assertEqual(s.get_node(item).state, "done")

    def test_add_project_creates_a_new_entry(self):
        s = self.make_store()
        s.add_project("acme/horde", shortcode="HORDE", local_path="/p/horde")
        p = s.get_project("acme/horde")
        self.assertEqual(p.identity, "acme/horde")
        self.assertEqual(p.shortcode, "HORDE")
        self.assertEqual(p.local_path, "/p/horde")
        self.assertIsNone(p.remote)

    def test_add_project_updating_one_field_leaves_others_alone(self):
        s = self.make_store()
        s.add_project("acme/horde", shortcode="HORDE", local_path="/p/horde")
        s.add_project("acme/horde", local_path="/p/horde-moved")
        p = s.get_project("acme/horde")
        self.assertEqual(p.shortcode, "HORDE")
        self.assertEqual(p.local_path, "/p/horde-moved")

    def test_get_project_returns_none_for_unknown_identity(self):
        s = self.make_store()
        self.assertIsNone(s.get_project("acme/ghost"))

    def test_list_projects_round_trips_every_entry(self):
        s = self.make_store()
        s.add_project("acme/horde", shortcode="HORDE", local_path="/p/horde")
        s.add_project("acme/saga", shortcode="SAGA", local_path="/p/saga")
        identities = {p.identity for p in s.list_projects()}
        self.assertEqual(identities, {"acme/horde", "acme/saga"})

    def test_remove_project_deletes_the_entry(self):
        s = self.make_store()
        s.add_project("acme/horde", shortcode="HORDE")
        s.remove_project("acme/horde")
        self.assertIsNone(s.get_project("acme/horde"))

    def test_remove_project_raises_key_error_on_unknown_identity(self):
        s = self.make_store()
        with self.assertRaises(KeyError):
            s.remove_project("acme/ghost")

    def test_resolve_project_path_passes_through_an_absolute_ref_without_a_lookup(self):
        s = self.make_store()
        self.assertEqual(s.resolve_project_path("/elsewhere/app"), "/elsewhere/app")

    def test_resolve_project_path_matches_the_exact_owner_slash_name_identity(self):
        s = self.make_store()
        s.add_project("acme/horde", local_path="/p/horde")
        self.assertEqual(s.resolve_project_path("acme/horde"), "/p/horde")

    def test_resolve_project_path_matches_an_unambiguous_bare_name(self):
        s = self.make_store()
        s.add_project("acme/horde", local_path="/p/horde")
        self.assertEqual(s.resolve_project_path("horde"), "/p/horde")

    def test_resolve_project_path_raises_on_an_unregistered_ref(self):
        s = self.make_store()
        with self.assertRaises(ProjectResolutionError):
            s.resolve_project_path("ghost")

    def test_resolve_project_path_raises_on_an_ambiguous_bare_name(self):
        s = self.make_store()
        s.add_project("acme/app", local_path="/p/acme-app")
        s.add_project("other/app", local_path="/p/other-app")
        with self.assertRaises(ProjectResolutionError):
            s.resolve_project_path("app")

    def test_resolve_project_path_raises_when_registered_without_a_local_checkout(self):
        s = self.make_store()
        s.add_project("acme/horde", shortcode="HORDE")
        with self.assertRaises(ProjectResolutionError) as ctx:
            s.resolve_project_path("horde")
        self.assertIn("activate the item to clone it automatically", str(ctx.exception))

    def test_find_project_matches_the_exact_owner_slash_name_identity(self):
        s = self.make_store()
        s.add_project("acme/horde", local_path="/p/horde")
        self.assertEqual(s.find_project("acme/horde").identity, "acme/horde")

    def test_find_project_matches_an_unambiguous_bare_name(self):
        s = self.make_store()
        s.add_project("acme/horde", local_path="/p/horde")
        self.assertEqual(s.find_project("horde").identity, "acme/horde")

    def test_find_project_raises_on_an_unregistered_ref(self):
        s = self.make_store()
        with self.assertRaises(ProjectResolutionError):
            s.find_project("ghost")

    def test_find_project_raises_on_an_ambiguous_bare_name(self):
        s = self.make_store()
        s.add_project("acme/app", local_path="/p/acme-app")
        s.add_project("other/app", local_path="/p/other-app")
        with self.assertRaises(ProjectResolutionError):
            s.find_project("app")

    def test_find_project_returns_the_entry_with_a_null_local_path_without_raising(self):
        s = self.make_store()
        s.add_project("acme/horde", shortcode="HORDE")
        project = s.find_project("horde")
        self.assertEqual(project.identity, "acme/horde")
        self.assertIsNone(project.local_path)

    def test_replace_artifact_only_replaces_the_matching_label(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "branch", "feat/spec", label="spec")
        s.add_artifact(sid, "branch", "feat/code", label="code")

        s.replace_artifact(sid, "branch", "feat/spec-2", label="spec")

        got = {(a.label, a.value) for a in s.item_artifacts(sid) if a.type == "branch"}
        self.assertEqual(got, {("spec", "feat/spec-2"), ("code", "feat/code")})

    def test_replace_artifact_without_a_label_leaves_labelled_ones_alone(self):
        s = self.make_store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "pr", "https://gh/spec", label="spec")
        s.add_artifact(sid, "pr", "https://gh/plain")

        s.replace_artifact(sid, "pr", "https://gh/plain-2")

        got = {(a.label, a.value) for a in s.item_artifacts(sid) if a.type == "pr"}
        self.assertEqual(got, {("spec", "https://gh/spec"), (None, "https://gh/plain-2")})

    def test_node_view_of_an_item_shows_its_own_artifacts(self):
        s = self.make_store()
        item = s.create_item("item: foo", "a description")
        s.add_artifact(item, "spec", "specs/foo.md")

        view = s.node_view(item)

        got = {(a.type, a.value) for a in view.item_artifacts}
        self.assertEqual(got, {("spec", "specs/foo.md")})

    def test_node_view_of_a_step_still_shows_its_parent_item_artifacts(self):
        s = self.make_store()
        item = s.create_item("item: foo", "a description")
        s.add_artifact(item, "spec", "specs/foo.md")
        step = self._step(s, "build: foo", parent=item)

        view = s.node_view(step)

        got = {(a.type, a.value) for a in view.item_artifacts}
        self.assertEqual(got, {("spec", "specs/foo.md")})
