import unittest

from lightcycle.application.work.hierarchy import HierarchyInput, HierarchyUseCase
from lightcycle.domain.runs import Pass, pass_number
from lightcycle.domain.work import (
    PassHeader, display_role, has_content, landing_tab, row_bucket, viewable_artifacts,
)
from tests.support.fake_store import FakeStore


class TestHierarchyUseCase(unittest.TestCase):
    def test_opening_from_a_step_roots_at_its_item(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        step = s.create_step("step", step="write-code", role="agent", parent=item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=step)).rows
        self.assertEqual([(r.node.id, r.depth) for r in rows], [(item, 0), (step, 1)])

    def test_an_items_siblings_are_not_shown(self):
        s = FakeStore()
        other = s.create_item("other", "a description")
        item = s.create_item("item", "a description")
        step = s.create_step("step", step="write-code", role="agent", parent=item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([r.node.id for r in rows], [item, step])
        self.assertNotIn(other, [r.node.id for r in rows])

    def test_an_item_is_its_own_root(self):
        s = FakeStore()
        item = s.create_item("solo", "a description")
        step = s.create_step("step", step="write-code", role="agent", parent=item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([(r.node.id, r.depth) for r in rows], [(item, 0), (step, 1)])

    def test_backlog_item_with_no_steps_shows_only_itself(self):
        s = FakeStore()
        item = s.create_item("solo", "a description")
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([r.node.id for r in rows], [item])

    def test_a_single_real_pass_still_renders_a_header(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        pid = s.open_pass(item)
        step1 = s.create_step("s1", step="feature-writer", role="agent", parent=item)
        s.set_step_pass(step1, pid)
        step2 = s.create_step("s2", step="implement-features", role="agent", parent=item)
        s.set_step_pass(step2, pid)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([(r.node.id, r.depth) for r in rows], [
            (item, 0), (pid, 1), (step1, 2), (step2, 2),
        ])
        self.assertIsInstance(rows[1].node, PassHeader)

    def test_two_passes_cluster_their_own_steps_under_their_own_header(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        pid1 = s.open_pass(item)
        step1 = s.create_step("s1", step="build", role="agent", parent=item)
        s.set_step_pass(step1, pid1)
        s.close_pass(pid1)
        pid2 = s.open_pass(item)
        step2 = s.create_step("s2", step="build", role="agent", parent=item)
        s.set_step_pass(step2, pid2)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([(r.node.id, r.depth) for r in rows], [
            (item, 0), (pid1, 1), (step1, 2), (pid2, 1), (step2, 2),
        ])

    def test_a_step_with_no_recorded_pass_falls_back_to_depth_one(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        legacy = s.create_step("legacy", step="build", role="agent", parent=item)
        pid = s.open_pass(item)
        enrolled = s.create_step("enrolled", step="build", role="agent", parent=item)
        s.set_step_pass(enrolled, pid)
        s.open_pass(item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([(r.node.id, r.depth) for r in rows], [
            (item, 0), (legacy, 1), (pid, 1), (enrolled, 2),
        ])

    def test_a_pass_with_no_enrolled_steps_produces_no_header(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.open_pass(item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([r.node.id for r in rows], [item])


class TestPassHeader(unittest.TestCase):
    def test_open_pass_bucket_is_active(self):
        header = PassHeader(Pass("LC-1.p1", "LC-1", 1, "open"))
        self.assertEqual(row_bucket(header), "active")

    def test_closed_pass_bucket_is_done(self):
        header = PassHeader(Pass("LC-1.p1", "LC-1", 1, "closed"))
        self.assertEqual(row_bucket(header), "done")

    def test_blocked_by_is_always_empty(self):
        header = PassHeader(Pass("LC-1.p1", "LC-1", 1, "open"))
        self.assertEqual(header.blocked_by, [])

    def test_has_no_content(self):
        header = PassHeader(Pass("LC-1.p1", "LC-1", 1, "open"))
        self.assertFalse(has_content(header))

    def test_title_names_its_pass_number(self):
        header = PassHeader(Pass("LC-1.p2", "LC-1", 2, "open"))
        self.assertEqual(header.title, "Pass 2")


class TestPassNumber(unittest.TestCase):
    def test_none_is_pass_one(self):
        self.assertEqual(pass_number(None), 1)

    def test_first_pass_id_is_one(self):
        self.assertEqual(pass_number("LC-1.p1"), 1)

    def test_second_pass_id_is_two(self):
        self.assertEqual(pass_number("LC-1.p2"), 2)


class TestLandingTab(unittest.TestCase):
    def test_item_lands_on_description(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertEqual(landing_tab(s.get_node(item)), "description")

    def test_active_step_lands_on_log(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="agent")
        s.claim_ready("agent")
        self.assertEqual(landing_tab(s.get_node(step)), "log")

    def test_needs_attention_human_step_lands_on_detail(self):
        s = FakeStore()
        step = s.create_step("s", step="await-merge", role="human")
        self.assertEqual(landing_tab(s.get_node(step)), "detail")

    def test_dependency_blocked_step_lands_on_detail(self):
        s = FakeStore()
        blocker = s.create_step("b", step="build", role="agent")
        step = s.create_step("s", step="build", role="agent", deps=[blocker])
        self.assertEqual(landing_tab(s.get_node(step)), "detail")

    def test_queued_step_lands_on_detail(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="agent")
        self.assertEqual(landing_tab(s.get_node(step)), "detail")

    def test_done_step_lands_on_detail(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="agent")
        s.close(step, "done")
        self.assertEqual(landing_tab(s.get_node(step)), "detail")

class TestRowBucket(unittest.TestCase):
    def test_dependency_blocked_step_is_queued(self):
        s = FakeStore()
        blocker = s.create_step("b", step="build", role="agent")
        step = s.create_step("s", step="build", role="agent", deps=[blocker])
        self.assertEqual(row_bucket(s.get_node(step)), "queued")

    def test_human_ready_step_is_needs_attention(self):
        s = FakeStore()
        step = s.create_step("s", step="await-merge", role="human")
        self.assertEqual(row_bucket(s.get_node(step)), "needs-attention")

    def test_queued_agent_step_is_queued(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="agent")
        self.assertEqual(row_bucket(s.get_node(step)), "queued")

    def test_in_progress_step_is_active(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="agent")
        s.claim_ready("agent")
        self.assertEqual(row_bucket(s.get_node(step)), "active")

    def test_done_step_is_done(self):
        s = FakeStore()
        step = s.create_step("s", step="build", role="agent")
        s.close(step, "done")
        self.assertEqual(row_bucket(s.get_node(step)), "done")

    def test_dependency_blocked_item_is_queued(self):
        s = FakeStore()
        blocker = s.create_item("blocker", "a description")
        item = s.create_item("blocked", "a description")
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
        item = s.create_item("item", "a description")
        s.add_artifact(item, "spec", "specs/x.md")
        self.assertTrue(has_content(s.get_node(item)))

    def test_only_internal_artifacts_is_no_content(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.add_artifact(item, "reflection", "text", internal=True)
        self.assertFalse(has_content(s.get_node(item)))

    def test_no_artifacts_is_no_content(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertFalse(has_content(s.get_node(item)))


class TestViewableArtifacts(unittest.TestCase):
    def test_internal_artifacts_are_excluded(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.add_artifact(item, "spec", "specs/x.md")
        s.add_artifact(item, "reflection", "text", internal=True)
        result = viewable_artifacts(s.get_node(item))
        self.assertEqual([a.type for a in result], ["spec"])

    def test_no_artifacts_is_an_empty_list(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertEqual(viewable_artifacts(s.get_node(item)), [])
