from lightcycle.domain.pool import AttributionEvent, ToolUsage, UsageEvent
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
        self.assertEqual(s.get_node(tid).state, "running")

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

    def test_stale_claimant_cannot_complete_after_reclaim(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        claimed = s.claim_ready("agent")
        spawnid = claimed.claimed_by
        s.reclaim(tid)
        won, _ = s.complete_step_atomic(tid, "done", spawnid, None)
        self.assertFalse(won)
        self.assertNotEqual(s.get_node(tid).state, "done")

    def test_human_can_close_a_reclaimed_step(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.claim_ready("agent")
        s.reclaim(tid)
        won, _ = s.complete_step_atomic(tid, "done", "", None)
        self.assertTrue(won)

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

    def test_assign_shows_running(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.assign(tid, "worker-1")
        self.assertEqual(s.get_node(tid).state, "running")

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

    def test_reassign_to_human_is_waiting(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.reassign(tid, "human")
        self.assertEqual(s.get_node(tid).state, "waiting")

    def test_reassign_to_an_agent_role_is_queued(self):
        s = self.make_store()
        tid = self._step(s, "t", role="human")
        s.reassign(tid, "some-agent-role")
        self.assertEqual(s.get_node(tid).state, "queued")

    def test_reclaim_is_queued(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.claim_ready("agent")
        s.reclaim(tid)
        self.assertEqual(s.get_node(tid).state, "queued")

    def test_reclaim_clears_assignee(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.claim_ready("agent")
        self.assertTrue(s.get_node(tid).claimed_by)
        s.reclaim(tid)
        self.assertFalse(s.get_node(tid).claimed_by)

    def test_reclaimed_step_is_claimable_again(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        claimed = s.claim_ready("agent")
        self.assertEqual(claimed.id, tid)
        s.reclaim(tid)
        reclaimed = s.claim_ready("agent")
        self.assertEqual(reclaimed.id, tid)

    def test_reassigned_to_human_then_back_to_agent_is_claimable_again(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        claimed = s.claim_ready("agent")
        self.assertEqual(claimed.id, tid)
        s.reassign(tid, "human")
        s.reassign(tid, "agent")
        reclaimed = s.claim_ready("agent")
        self.assertEqual(reclaimed.id, tid)

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

    def test_new_step_has_no_active_seconds(self):
        s = self.make_store()
        tid = self._step(s, "t")
        t = s.get_node(tid)
        self.assertIsNone(t.active_seconds)
        self.assertIsNone(t.as_dict()["active_seconds"])

    def test_accrue_active_seconds_accumulates_not_overwrites(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.accrue_active_seconds([tid], 5.0)
        self.assertEqual(s.get_node(tid).active_seconds, 5.0)
        s.accrue_active_seconds([tid], 2.5)
        self.assertEqual(s.get_node(tid).active_seconds, 7.5)

    def test_accrue_active_seconds_credits_every_id_the_same_delta(self):
        s = self.make_store()
        tid_a = self._step(s, "a")
        tid_b = self._step(s, "b")
        s.accrue_active_seconds([tid_a, tid_b], 4.0)
        self.assertEqual(s.get_node(tid_a).active_seconds, 4.0)
        self.assertEqual(s.get_node(tid_b).active_seconds, 4.0)

    def test_accrue_active_seconds_empty_ids_is_a_noop(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.accrue_active_seconds([], 5.0)
        self.assertIsNone(s.get_node(tid).active_seconds)

    def test_accrue_active_seconds_unknown_id_does_not_raise(self):
        s = self.make_store()
        s.accrue_active_seconds(["unknown-id"], 5.0)

    def test_new_step_has_zeroed_usage(self):
        s = self.make_store()
        tid = self._step(s, "t")
        t = s.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 0)
        self.assertEqual(t.usage_output_tokens, 0)
        self.assertEqual(t.usage_cache_read_tokens, 0)
        self.assertEqual(t.usage_cache_creation_tokens, 0)
        self.assertEqual(t.usage_cost_usd, 0.0)
        self.assertIsNone(t.usage_cost_basis)
        self.assertIsNone(t.usage_thinking_tokens)

    def test_record_usage_roundtrips_all_seven_fields(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_usage(tid, 10, 20, 30, 40, 1.5, "list", 5)
        t = s.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 10)
        self.assertEqual(t.usage_output_tokens, 20)
        self.assertEqual(t.usage_cache_read_tokens, 30)
        self.assertEqual(t.usage_cache_creation_tokens, 40)
        self.assertEqual(t.usage_cost_usd, 1.5)
        self.assertEqual(t.usage_cost_basis, "list")
        self.assertEqual(t.usage_thinking_tokens, 5)

    def test_record_usage_second_call_adds_to_the_numeric_fields(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_usage(tid, 10, 20, 30, 40, 1.5, None, None)
        s.record_usage(tid, 1, 2, 3, 4, 0.5, None, None)
        t = s.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 11)
        self.assertEqual(t.usage_output_tokens, 22)
        self.assertEqual(t.usage_cache_read_tokens, 33)
        self.assertEqual(t.usage_cache_creation_tokens, 44)
        self.assertEqual(t.usage_cost_usd, 2.0)

    def test_record_usage_none_cost_basis_and_thinking_tokens_leave_prior_values_untouched(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_usage(tid, 1, 1, 1, 1, 1.0, "list", 5)
        s.record_usage(tid, 1, 1, 1, 1, 1.0, None, None)
        t = s.get_node(tid)
        self.assertEqual(t.usage_cost_basis, "list")
        self.assertEqual(t.usage_thinking_tokens, 5)

    def test_record_usage_first_none_then_real_values_moves_off_null(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_usage(tid, 1, 1, 1, 1, 1.0, None, None)
        s.record_usage(tid, 1, 1, 1, 1, 1.0, "list", 5)
        t = s.get_node(tid)
        self.assertEqual(t.usage_cost_basis, "list")
        self.assertEqual(t.usage_thinking_tokens, 5)

    def test_record_attribution_roundtrips_turn_count_and_tool_usage(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_attribution(tid, 3, {"Read": ToolUsage(calls=2, bytes=100)})
        t = s.get_node(tid)
        self.assertEqual(t.turn_count, 3)
        self.assertEqual(s.tool_usage_for(tid), {"Read": ToolUsage(calls=2, bytes=100)})

    def test_record_attribution_second_call_adds_to_turn_count_and_existing_tool_rows(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_attribution(tid, 3, {"Read": ToolUsage(calls=2, bytes=100)})
        s.record_attribution(tid, 1, {"Read": ToolUsage(calls=1, bytes=50)})
        t = s.get_node(tid)
        self.assertEqual(t.turn_count, 4)
        self.assertEqual(s.tool_usage_for(tid), {"Read": ToolUsage(calls=3, bytes=150)})

    def test_record_attribution_new_tool_adds_a_row_without_disturbing_existing_ones(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_attribution(tid, 1, {"Read": ToolUsage(calls=1, bytes=10)})
        s.record_attribution(tid, 1, {"Grep": ToolUsage(calls=1, bytes=5)})
        usage = s.tool_usage_for(tid)
        self.assertEqual(usage["Read"], ToolUsage(calls=1, bytes=10))
        self.assertEqual(usage["Grep"], ToolUsage(calls=1, bytes=5))

    def test_record_backfilled_usage_with_step_id_writes_usage_attribution_and_ledger(self):
        s = self.make_store()
        tid = self._step(s, "t")
        usage = UsageEvent(input_tokens=5, output_tokens=6, cost_usd=1.0, cost_basis="list")
        attribution = AttributionEvent(turn_count=2, tool_usage={"Read": ToolUsage(calls=1, bytes=10)})
        stored = s.record_backfilled_usage("/l/x.log", tid, usage, attribution)
        self.assertTrue(stored)
        t = s.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 5)
        self.assertEqual(t.turn_count, 2)
        self.assertEqual(s.tool_usage_for(tid), {"Read": ToolUsage(calls=1, bytes=10)})
        self.assertIn("/l/x.log", s.usage_backfilled_logs())

    def test_record_backfilled_usage_with_none_step_id_writes_only_the_ledger_row(self):
        s = self.make_store()
        usage = UsageEvent()
        attribution = AttributionEvent()
        stored = s.record_backfilled_usage("/l/unmatched.log", None, usage, attribution)
        self.assertFalse(stored)
        self.assertIn("/l/unmatched.log", s.usage_backfilled_logs())

    def test_record_backfilled_usage_with_orphaned_step_id_reports_unstored_and_writes_only_the_ledger_row(self):
        s = self.make_store()
        usage = UsageEvent(input_tokens=5, output_tokens=6, cost_usd=1.0, cost_basis="list")
        attribution = AttributionEvent(turn_count=2, tool_usage={"Read": ToolUsage(calls=1, bytes=10)})
        stored = s.record_backfilled_usage("/l/orphaned.log", "does-not-exist", usage, attribution)
        self.assertFalse(stored)
        self.assertIn("/l/orphaned.log", s.usage_backfilled_logs())
        self.assertEqual(s.tool_usage_for("does-not-exist"), {})

    def test_record_backfilled_usage_replayed_log_file_is_a_noop(self):
        s = self.make_store()
        tid = self._step(s, "t")
        usage = UsageEvent(input_tokens=5, output_tokens=6, cost_usd=1.0, cost_basis="list")
        attribution = AttributionEvent(turn_count=2, tool_usage={"Read": ToolUsage(calls=1, bytes=10)})
        s.record_backfilled_usage("/l/x.log", tid, usage, attribution)
        stored = s.record_backfilled_usage("/l/x.log", tid, usage, attribution)
        self.assertFalse(stored)
        t = s.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 5)
        self.assertEqual(t.turn_count, 2)

    def test_usage_accrual_state_absent_for_unknown_spawnid(self):
        s = self.make_store()
        self.assertIsNone(s.usage_accrual_state("nope"))

    def test_record_live_usage_checkpoints_and_applies_deltas_atomically(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_live_usage(
            spawnid="sp1", log_file="/l/x.log", offset=100, message_ids=["m1"],
            pending_tool_use={}, posted_turn_count=1,
            posted_tool_usage={"Read": {"calls": 1, "bytes": 10}},
            posted_input_tokens=5, posted_output_tokens=6, posted_cache_read_tokens=0,
            posted_cache_creation_tokens=0, posted_cost_usd=1.0,
            tid=tid, input_tokens=5, output_tokens=6, cache_read_tokens=0,
            cache_creation_tokens=0, cost_usd=1.0, cost_basis="list", thinking_tokens=None,
            turn_count=1, tool_usage={"Read": ToolUsage(calls=1, bytes=10)},
        )
        state = s.usage_accrual_state("sp1")
        self.assertEqual(state["offset"], 100)
        self.assertEqual(state["message_ids"], ["m1"])
        self.assertEqual(state["posted_input_tokens"], 5)
        t = s.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 5)
        self.assertEqual(t.turn_count, 1)

    def test_record_live_usage_overwrites_prior_checkpoint_for_same_spawnid(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_live_usage(
            spawnid="sp1", log_file="/l/x.log", offset=100, message_ids=["m1"],
            pending_tool_use={}, posted_turn_count=1, posted_tool_usage={},
            posted_input_tokens=5, posted_output_tokens=0, posted_cache_read_tokens=0,
            posted_cache_creation_tokens=0, posted_cost_usd=0.0,
            tid=tid, input_tokens=5, output_tokens=0, cache_read_tokens=0,
            cache_creation_tokens=0, cost_usd=0.0, cost_basis=None, thinking_tokens=None,
            turn_count=0, tool_usage={},
        )
        s.record_live_usage(
            spawnid="sp1", log_file="/l/x.log", offset=200, message_ids=["m1", "m2"],
            pending_tool_use={}, posted_turn_count=1, posted_tool_usage={},
            posted_input_tokens=10, posted_output_tokens=0, posted_cache_read_tokens=0,
            posted_cache_creation_tokens=0, posted_cost_usd=0.0,
            tid=tid, input_tokens=5, output_tokens=0, cache_read_tokens=0,
            cache_creation_tokens=0, cost_usd=0.0, cost_basis=None, thinking_tokens=None,
            turn_count=0, tool_usage={},
        )
        state = s.usage_accrual_state("sp1")
        self.assertEqual(state["offset"], 200)
        self.assertEqual(state["message_ids"], ["m1", "m2"])
        t = s.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 10)

    def test_clear_usage_accrual_state_removes_the_row(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_live_usage(
            spawnid="sp1", log_file="/l/x.log", offset=100, message_ids=[],
            pending_tool_use={}, posted_turn_count=0, posted_tool_usage={},
            posted_input_tokens=0, posted_output_tokens=0, posted_cache_read_tokens=0,
            posted_cache_creation_tokens=0, posted_cost_usd=0.0,
            tid=tid, input_tokens=0, output_tokens=0, cache_read_tokens=0,
            cache_creation_tokens=0, cost_usd=0.0, cost_basis=None, thinking_tokens=None,
            turn_count=0, tool_usage={},
        )
        s.clear_usage_accrual_state("sp1")
        self.assertIsNone(s.usage_accrual_state("sp1"))

    def test_usage_backfilled_logs_reflects_every_log_passed_matched_or_not(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_backfilled_usage("/l/matched.log", tid, UsageEvent(), AttributionEvent())
        s.record_backfilled_usage("/l/unmatched.log", None, UsageEvent(), AttributionEvent())
        self.assertEqual(
            s.usage_backfilled_logs(), {"/l/matched.log", "/l/unmatched.log"}
        )

    def test_record_backfilled_usage_writes_had_result_line_matching_the_usage_event(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_backfilled_usage(
            "/l/with-result.log", tid, UsageEvent(has_result_line=True), AttributionEvent()
        )
        s.record_backfilled_usage(
            "/l/without-result.log", tid, UsageEvent(has_result_line=False), AttributionEvent()
        )
        self.assertEqual(s.unclassified_backfill_logs(), [])

    def test_unclassified_backfill_logs_returns_only_rows_with_no_classification(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_backfilled_usage(
            "/l/classified.log", tid, UsageEvent(has_result_line=True), AttributionEvent()
        )
        s._seed_unclassified_backfill_row("/l/unclassified.log", tid)
        self.assertEqual(s.unclassified_backfill_logs(), [("/l/unclassified.log", tid)])

    def test_reclassify_with_a_result_line_only_flips_classification_leaving_usage_untouched(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_usage(tid, 1, 1, 1, 1, 1.0, "list", None)
        s._seed_unclassified_backfill_row("/l/x.log", tid)
        before = s.get_node(tid).usage_cost_usd

        recovered = s.reclassify_backfilled_log(
            "/l/x.log", tid, UsageEvent(has_result_line=True), AttributionEvent()
        )

        self.assertFalse(recovered)
        after = s.get_node(tid).usage_cost_usd
        self.assertEqual(before, after)
        self.assertEqual(s.unclassified_backfill_logs(), [])

    def test_reclassify_with_no_result_line_adds_usage_and_flips_classification(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s._seed_unclassified_backfill_row("/l/x.log", tid)
        usage = UsageEvent(input_tokens=5, output_tokens=6, cost_usd=1.0, cost_basis="derived")
        attribution = AttributionEvent(turn_count=2, tool_usage={"Read": ToolUsage(calls=1, bytes=10)})

        recovered = s.reclassify_backfilled_log("/l/x.log", tid, usage, attribution)

        self.assertTrue(recovered)
        t = s.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 5)
        self.assertEqual(s.unclassified_backfill_logs(), [])

    def test_logs_for_step_returns_exactly_the_ledgered_logs_for_that_step_and_nothing_else(self):
        s = self.make_store()
        tid = self._step(s, "t")
        other = self._step(s, "other")
        s.record_backfilled_usage("/l/a.log", tid, UsageEvent(), AttributionEvent())
        s.record_backfilled_usage("/l/b.log", tid, UsageEvent(), AttributionEvent())
        s.record_backfilled_usage("/l/c.log", other, UsageEvent(), AttributionEvent())
        self.assertEqual(set(s.logs_for_step(tid)), {"/l/a.log", "/l/b.log"})
        self.assertEqual(set(s.logs_for_step(other)), {"/l/c.log"})

    def test_logs_for_step_returns_empty_for_a_step_with_no_ledger_rows(self):
        s = self.make_store()
        tid = self._step(s, "t")
        self.assertEqual(s.logs_for_step(tid), [])

    def test_overwrite_usage_and_attribution_replaces_rather_than_adds(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_usage(tid, 100, 100, 100, 100, 10.0, "list", 5)
        s.record_attribution(tid, 9, {"Read": ToolUsage(calls=9, bytes=90)})
        usage_totals = UsageEvent(
            input_tokens=1, output_tokens=2, cache_read_tokens=3, cache_creation_tokens=4,
            cost_usd=0.5, cost_basis="derived", thinking_tokens=6,
        )
        s.overwrite_usage_and_attribution(tid, usage_totals, 1, {"Bash": ToolUsage(calls=1, bytes=10)})
        t = s.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 1)
        self.assertEqual(t.usage_output_tokens, 2)
        self.assertEqual(t.usage_cache_read_tokens, 3)
        self.assertEqual(t.usage_cache_creation_tokens, 4)
        self.assertEqual(t.usage_cost_usd, 0.5)
        self.assertEqual(t.usage_cost_basis, "derived")
        self.assertEqual(t.usage_thinking_tokens, 6)
        self.assertEqual(t.turn_count, 1)
        self.assertEqual(s.tool_usage_for(tid), {"Bash": ToolUsage(calls=1, bytes=10)})

    def test_overwrite_usage_and_attribution_drops_a_tool_absent_from_the_new_totals(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_attribution(tid, 1, {"Read": ToolUsage(calls=1, bytes=10)})
        s.overwrite_usage_and_attribution(tid, UsageEvent(), 1, {"Bash": ToolUsage(calls=1, bytes=5)})
        usage = s.tool_usage_for(tid)
        self.assertNotIn("Read", usage)
        self.assertEqual(usage, {"Bash": ToolUsage(calls=1, bytes=5)})

    def test_reclassify_leaves_attribution_already_recorded_at_original_ingest_untouched(self):
        s = self.make_store()
        tid = self._step(s, "t")
        s.record_attribution(tid, 246, {"Read": ToolUsage(calls=3, bytes=100)})
        s._seed_unclassified_backfill_row("/l/x.log", tid)
        usage = UsageEvent(input_tokens=5, output_tokens=6, cost_usd=1.0, cost_basis="derived")
        attribution = AttributionEvent(
            turn_count=246, tool_usage={"Read": ToolUsage(calls=3, bytes=100)}
        )

        recovered = s.reclassify_backfilled_log("/l/x.log", tid, usage, attribution)

        self.assertTrue(recovered)
        t = s.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 5)
        self.assertEqual(t.turn_count, 246)
        self.assertEqual(s.tool_usage_for(tid), {"Read": ToolUsage(calls=3, bytes=100)})

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
        self.assertEqual(states, ["running", "done"])

    def test_history_stamps_ts_from_injected_clock(self):
        ticks = iter("2026-01-01T%02d:00:00" % h for h in range(10, 20))
        s = self.make_store(now=lambda: next(ticks))
        tid = self._step(s, "t", role="agent")
        s.claim_ready("agent")
        s.close(tid, "done")
        stamps = [ts for _, ts in s.history(tid)]
        self.assertEqual(len(stamps), 2)
        self.assertTrue(all(ts.startswith("2026-01-01T1") for ts in stamps))
        self.assertLess(stamps[0], stamps[1])

    def test_history_empty_for_unclaimed_task(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        self.assertEqual(s.history(tid), [])

    def test_steps_at_step_created_at_set_and_orders_by_creation(self):
        s = self.make_store()
        item = s.create_item("owner", "an owning item")
        first = s.create_step("first", step="build", role="agent", parent=item)
        second = s.create_step("second", step="build", role="agent", parent=item)
        steps = {t.id: t for t in s.steps_at_step("build")}
        self.assertTrue(steps[first].created_at)
        self.assertTrue(steps[second].created_at)
        ordered = sorted(steps.values(), key=lambda t: t.created_at)
        self.assertEqual([t.id for t in ordered], [first, second])

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

    def test_step_state_blocked_when_it_has_unresolved_deps(self):
        s = self.make_store()
        blocker = self._step(s, "blocker")
        blocked = self._step(s, "blocked", deps=[blocker])
        self.assertEqual(s.get_node(blocked).state, "blocked")

    def test_step_state_running_when_assigned_despite_deps(self):
        s = self.make_store()
        blocker = self._step(s, "blocker")
        blocked = self._step(s, "blocked", deps=[blocker])
        s.assign(blocked, "w1")
        self.assertEqual(s.get_node(blocked).state, "running")

    def test_step_state_done_when_closed(self):
        s = self.make_store()
        blocker = self._step(s, "blocker")
        blocked = self._step(s, "blocked", deps=[blocker])
        s.assign(blocked, "w1")
        s.close(blocked, "done")
        self.assertEqual(s.get_node(blocked).state, "done")

    def test_step_state_queued_when_unblocked(self):
        s = self.make_store()
        blocker = self._step(s, "blocker", role="agent")
        blocked = self._step(s, "blocked", role="agent", deps=[blocker])
        s.close(blocker, "done")
        self.assertEqual(s.get_node(blocked).state, "queued")

    def test_step_state_queued_when_blocker_deleted(self):
        s = self.make_store()
        blocker = self._step(s, "blocker", role="agent")
        blocked = self._step(s, "blocked", role="agent", deps=[blocker])
        s.delete(blocker)
        self.assertEqual(s.get_node(blocked).state, "queued")

    def test_item_state_rolls_up_mixed_children(self):
        s = self.make_store()
        item = s.create_item("item", "a description")
        done_step = self._step(s, "done step", role="agent", parent=item)
        self._step(s, "open step", role="agent", parent=item)
        s.close(done_step, "done")
        self.assertEqual(s.get_node(item).state, "queued")

    def test_item_state_done_when_all_children_done(self):
        s = self.make_store()
        item = s.create_item("item", "a description")
        a = self._step(s, "a", parent=item)
        b = self._step(s, "b", parent=item)
        s.close(a, "done")
        s.close(b, "done")
        self.assertEqual(s.get_node(item).state, "done")

    def test_item_state_queued_when_all_children_queued(self):
        s = self.make_store()
        item = s.create_item("item", "a description")
        self._step(s, "a", role="agent", parent=item)
        self._step(s, "b", role="agent", parent=item)
        self.assertEqual(s.get_node(item).state, "queued")

    def test_empty_item_state_backlogged(self):
        s = self.make_store()
        item = s.create_item("item", "a description")
        self.assertEqual(s.get_node(item).state, "backlogged")

    def test_step_state_queued_when_in_progress_column_but_unassigned(self):
        s = self.make_store()
        tid = self._step(s, "t", role="agent")
        s.update_state(tid, "in_progress")
        self.assertEqual(s.get_node(tid).state, "queued")

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
