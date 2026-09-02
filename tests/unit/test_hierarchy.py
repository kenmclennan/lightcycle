import unittest

from lightcycle.application.work.hierarchy import HierarchyInput, HierarchyUseCase
from lightcycle.domain.work import (
    display_role, has_content, landing_tab, row_bucket, viewable_artifacts,
)
from tests.support.fake_store import FakeStore


class TestHierarchyUseCase(unittest.TestCase):
    def test_opening_from_a_step_roots_at_its_item(self):
        s = FakeStore()
        item = s.create_item("item")
        step = s.create_step("step", step="write-code", role="write-code", parent=item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=step)).rows
        self.assertEqual([(r.node.id, r.depth) for r in rows], [(item, 0), (step, 1)])

    def test_an_items_siblings_are_not_shown(self):
        s = FakeStore()
        other = s.create_item("other")
        item = s.create_item("item")
        step = s.create_step("step", step="write-code", role="write-code", parent=item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([r.node.id for r in rows], [item, step])
        self.assertNotIn(other, [r.node.id for r in rows])

    def test_an_item_is_its_own_root(self):
        s = FakeStore()
        item = s.create_item("solo")
        step = s.create_step("step", step="write-code", role="write-code", parent=item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([(r.node.id, r.depth) for r in rows], [(item, 0), (step, 1)])

    def test_backlog_item_with_no_steps_shows_only_itself(self):
        s = FakeStore()
        item = s.create_item("solo")
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([r.node.id for r in rows], [item])

class TestLandingTab(unittest.TestCase):
    def test_active_lands_on_log(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="coder")
        s.claim_ready("coder")
        self.assertEqual(landing_tab(s.get_node(step)), "log")

    def test_needs_attention_human_step_lands_on_artifacts(self):
        s = FakeStore()
        step = s.create_step("s", step="await-merge", role="human")
        self.assertEqual(landing_tab(s.get_node(step)), "artifacts")

    def test_dependency_blocked_lands_on_hierarchy(self):
        s = FakeStore()
        blocker = s.create_step("b", step="build", role="coder")
        step = s.create_step("s", step="build", role="coder", deps=[blocker])
        self.assertEqual(landing_tab(s.get_node(step)), "hierarchy")

    def test_queued_lands_on_hierarchy(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="coder")
        self.assertEqual(landing_tab(s.get_node(step)), "hierarchy")

    def test_done_lands_on_artifacts(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="coder")
        s.close(step, "done")
        self.assertEqual(landing_tab(s.get_node(step)), "artifacts")

class TestRowBucket(unittest.TestCase):
    def test_dependency_blocked_step_is_queued(self):
        s = FakeStore()
        blocker = s.create_step("b", step="build", role="coder")
        step = s.create_step("s", step="build", role="coder", deps=[blocker])
        self.assertEqual(row_bucket(s.get_node(step)), "queued")

    def test_human_ready_step_is_needs_attention(self):
        s = FakeStore()
        step = s.create_step("s", step="await-merge", role="human")
        self.assertEqual(row_bucket(s.get_node(step)), "needs-attention")

    def test_queued_agent_step_is_queued(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="coder")
        self.assertEqual(row_bucket(s.get_node(step)), "queued")

    def test_in_progress_step_is_active(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="coder")
        s.claim_ready("coder")
        self.assertEqual(row_bucket(s.get_node(step)), "active")

    def test_done_step_is_done(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="coder")
        s.close(step, "done")
        self.assertEqual(row_bucket(s.get_node(step)), "done")

    def test_dependency_blocked_item_is_queued(self):
        s = FakeStore()
        blocker = s.create_item("blocker")
        item = s.create_item("blocked")
        s.dep_add(item, blocker)
        self.assertEqual(row_bucket(s.get_node(item)), "queued")


class TestDisplayRole(unittest.TestCase):
    def test_human_role_shown_as_human(self):
        self.assertEqual(display_role("human"), "human")

    def test_missing_role_falls_back_to_human(self):
        self.assertEqual(display_role(None), "human")

    def test_agent_role_shown_as_is(self):
        self.assertEqual(display_role("write-code"), "write-code")


class TestHasContent(unittest.TestCase):
    def test_non_internal_artifact_is_content(self):
        s = FakeStore()
        item = s.create_item("item")
        s.add_artifact(item, "repo", "org/repo")
        self.assertTrue(has_content(s.get_node(item)))

    def test_only_internal_artifacts_is_no_content(self):
        s = FakeStore()
        item = s.create_item("item")
        s.add_artifact(item, "reflection", "text", internal=True)
        self.assertFalse(has_content(s.get_node(item)))

    def test_no_artifacts_is_no_content(self):
        s = FakeStore()
        item = s.create_item("item")
        self.assertFalse(has_content(s.get_node(item)))


class TestViewableArtifacts(unittest.TestCase):
    def test_internal_artifacts_are_excluded(self):
        s = FakeStore()
        item = s.create_item("item")
        s.add_artifact(item, "repo", "org/repo")
        s.add_artifact(item, "reflection", "text", internal=True)
        result = viewable_artifacts(s.get_node(item))
        self.assertEqual([a.type for a in result], ["repo"])

    def test_no_artifacts_is_an_empty_list(self):
        s = FakeStore()
        item = s.create_item("item")
        self.assertEqual(viewable_artifacts(s.get_node(item)), [])
