import unittest

from lightcycle.application.work.backlog import (
    BacklogCountsResponse,
    BacklogInput,
    BacklogUseCase,
)
from lightcycle.application.work.project_counts import ProjectCount
from tests.support.fake_store import FakeStore


class TestBacklogDefault(unittest.TestCase):
    def test_returns_backlogged_items_sorted_by_id_with_project(self):
        s = FakeStore()
        b = s.create_item("b item", "a description", project="proj-b")
        a = s.create_item("a item", "a description", project="proj-a")
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertEqual([r.step.id for r in resp.rows], sorted([a, b]))
        by_id = {r.step.id: r.project for r in resp.rows}
        self.assertEqual(by_id[a], "proj-a")
        self.assertEqual(by_id[b], "proj-b")

    def test_orders_a_two_digit_suffix_after_a_one_digit_suffix(self):
        s = FakeStore()
        s.create_item("ten", "a description", id="proj-10")
        s.create_item("nine", "a description", id="proj-9")
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertEqual([r.step.id for r in resp.rows], ["proj-9", "proj-10"])

    def test_item_without_project_has_project_none(self):
        s = FakeStore()
        s.create_item("no project", "a description")
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertIsNone(resp.rows[0].project)

    def test_row_shows_project_and_repo_independently(self):
        s = FakeStore()
        item = s.create_item("item", "a description", project="proj-a")
        s.add_artifact(item, "repo", "org/repo-a")
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertEqual(resp.rows[0].project, "proj-a")
        self.assertEqual(resp.rows[0].repo, "org/repo-a")

    def test_row_with_repo_but_no_project_does_not_leak_into_project(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.add_artifact(item, "repo", "org/repo-a")
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertIsNone(resp.rows[0].project)
        self.assertEqual(resp.rows[0].repo, "org/repo-a")


class TestBacklogBlockedItems(unittest.TestCase):
    def test_unactivated_item_with_unresolved_dep_still_appears(self):
        s = FakeStore()
        blocker = s.create_item("blocker", "a description")
        held = s.create_item("held", "a description")
        s.dep_add(held, blocker)
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertIn(held, [r.step.id for r in resp.rows])

    def test_row_for_a_blocked_item_shows_what_it_is_waiting_on(self):
        s = FakeStore()
        blocker = s.create_item("blocker", "a description")
        held = s.create_item("held", "a description")
        s.dep_add(held, blocker)
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        row = next(r for r in resp.rows if r.step.id == held)
        self.assertEqual(row.step.blocked_by, [blocker])

    def test_activated_item_with_unresolved_dep_stays_excluded(self):
        s = FakeStore()
        blocker = s.create_item("blocker", "a description")
        item = s.create_item("in flight", "a description")
        s.create_step(parent=item, role="agent")
        s.dep_add(item, blocker)
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertNotIn(item, [r.step.id for r in resp.rows])

    def test_removing_the_dependency_leaves_it_a_plain_backlogged_row(self):
        s = FakeStore()
        blocker = s.create_item("blocker", "a description")
        held = s.create_item("held", "a description")
        s.dep_add(held, blocker)
        s.dep_remove(held, blocker)
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        row = next(r for r in resp.rows if r.step.id == held)
        self.assertEqual(row.step.blocked_by, [])


class TestBacklogProjectFilter(unittest.TestCase):
    def test_filters_to_matching_project(self):
        s = FakeStore()
        keep = s.create_item("keep", "a description", project="proj-a")
        s.create_item("drop", "a description", project="proj-b")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_item_without_project_is_excluded(self):
        s = FakeStore()
        s.create_item("no project", "a description")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a"))
        self.assertEqual(resp.rows, [])

    def test_item_whose_project_matches_but_repo_differs_is_included(self):
        s = FakeStore()
        item = s.create_item("item", "a description", project="proj-a")
        s.add_artifact(item, "repo", "org/proj-b")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a"))
        self.assertEqual([r.step.id for r in resp.rows], [item])

    def test_item_whose_repo_matches_but_project_differs_is_excluded(self):
        s = FakeStore()
        item = s.create_item("item", "a description", project="proj-b")
        s.add_artifact(item, "repo", "org/proj-a")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a"))
        self.assertEqual(resp.rows, [])


class TestBacklogTextFilter(unittest.TestCase):
    def test_matches_by_id_substring_case_insensitive(self):
        s = FakeStore()
        keep = s.create_item("keep", "a description", id="LC-479")
        s.create_item("drop", "a description", id="LC-999")
        resp = BacklogUseCase(s, None).execute(BacklogInput(text="lc-479"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_matches_by_title_substring_case_insensitive(self):
        s = FakeStore()
        keep = s.create_item("Filter the backlog", "a description")
        s.create_item("unrelated title", "a description")
        resp = BacklogUseCase(s, None).execute(BacklogInput(text="BACKLOG"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_matches_by_project_substring_case_insensitive(self):
        s = FakeStore()
        keep = s.create_item("keep", "a description", project="kenmclennan/lightcycle")
        s.create_item("drop", "a description")
        resp = BacklogUseCase(s, None).execute(BacklogInput(text="LIGHTCYCLE"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_mixed_matches_and_non_matches_returns_only_the_matches(self):
        s = FakeStore()
        keep_a = s.create_item("alpha widget", "a description")
        keep_b = s.create_item("beta thing", "a description", project="widget-co")
        s.create_item("gamma unrelated", "a description")
        resp = BacklogUseCase(s, None).execute(BacklogInput(text="widget"))
        self.assertEqual(sorted(r.step.id for r in resp.rows), sorted([keep_a, keep_b]))

    def test_project_and_text_compose_to_the_intersection(self):
        s = FakeStore()
        keep = s.create_item("target item", "a description", project="proj-a")
        s.create_item("target item", "a description", project="proj-b")
        s.create_item("other item", "a description", project="proj-a")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a", text="target"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_counts_are_unaffected_by_text(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.create_item("target item", "a description", project="proj-a")
        s.create_item("other item", "a description", project="proj-a")
        resp = BacklogUseCase(s, None).counts()
        by_project = {p.project: p.count for p in resp.projects}
        self.assertEqual(by_project, {"proj-a": 2})


class TestBacklogN(unittest.TestCase):
    def test_n_limits_project_filtered_items_before_grouping(self):
        s = FakeStore()
        a = s.create_item("a", "a description", project="proj-a")
        b = s.create_item("b", "a description", project="proj-a")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a", n=1))
        self.assertEqual(len(resp.rows), 1)
        self.assertEqual(resp.rows[0].step.id, sorted([a, b])[0])


class TestBacklogCounts(unittest.TestCase):
    def test_mixed_projects_and_unscoped(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.add_project("org-b/proj-b")
        s.add_project("org-c/proj-c")
        s.create_item("a1", "a description", project="proj-a")
        s.create_item("a2", "a description", project="proj-a")
        s.create_item("b1", "a description", project="proj-b")
        s.create_item("no project", "a description")
        resp = BacklogUseCase(s, None).counts()
        by_project = {p.project: p.count for p in resp.projects}
        self.assertEqual(by_project, {"proj-a": 2, "proj-b": 1, "proj-c": 0})
        self.assertEqual(resp.unscoped, 1)

    def test_project_with_zero_items_still_appears(self):
        s = FakeStore()
        s.add_project("org-c/proj-c")
        resp = BacklogUseCase(s, None).counts()
        self.assertEqual(resp.projects, [ProjectCount(project="proj-c", count=0)])

    def test_matched_by_bare_last_segment_of_identity(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.create_item("item", "a description", project="proj-a")
        resp = BacklogUseCase(s, None).counts()
        self.assertEqual(resp.projects, [ProjectCount(project="proj-a", count=1)])

    def test_a_bare_registered_identity_is_counted_without_raising(self):
        s = FakeStore()
        s.add_project("specs")
        s.create_item("item", "a description", project="specs")
        resp = BacklogUseCase(s, None).counts()
        self.assertEqual(resp.projects, [ProjectCount(project="specs", count=1)])

    def test_project_value_round_trips_into_execute_filter(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.add_project("org-b/proj-b")
        s.create_item("a1", "a description", project="proj-a")
        s.create_item("a2", "a description", project="proj-a")
        s.create_item("b1", "a description", project="proj-b")
        uc = BacklogUseCase(s, None)
        counts = uc.counts()
        for p in counts.projects:
            resp = uc.execute(BacklogInput(project=p.project))
            self.assertEqual(len(resp.rows), p.count)

    def test_total_includes_items_matching_no_registered_project(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.add_project("org-b/proj-b")
        s.create_item("a1", "a description", project="proj-a")
        s.create_item("a2", "a description", project="proj-a")
        s.create_item("b1", "a description", project="proj-b")
        s.create_item("no project", "a description")
        s.create_item("typo", "a description", project="typo-project")
        resp = BacklogUseCase(s, None).counts()
        self.assertEqual(resp.total, 5)
        bucketed = sum(p.count for p in resp.projects) + resp.unscoped
        self.assertGreater(resp.total, bucketed)

    def test_empty_store_returns_empty_counts(self):
        s = FakeStore()
        resp = BacklogUseCase(s, None).counts()
        self.assertEqual(resp, BacklogCountsResponse(projects=[], unscoped=0, total=0))

    def test_slash_qualified_project_is_counted_and_matched_by_its_registered_project(self):
        s = FakeStore()
        s.add_project("org/proj")
        item = s.create_item("item", "a description", project="org/proj")
        resp = BacklogUseCase(s, None).counts()
        self.assertEqual(resp.projects, [ProjectCount(project="proj", count=1)])
        filtered = BacklogUseCase(s, None).execute(BacklogInput(project="proj"))
        self.assertEqual([r.step.id for r in filtered.rows], [item])

    def test_counts_does_not_call_get_item(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.add_project("org-b/proj-b")
        s.create_item("item", "a description", project="proj-a")
        calls = {"n": 0}
        original = s.get_item

        def counted(tid):
            calls["n"] += 1
            return original(tid)

        s.get_item = counted
        BacklogUseCase(s, None).counts()
        self.assertEqual(calls["n"], 0)


class TestBacklogUseCaseMemoization(unittest.TestCase):
    def _counting_store(self):
        s = FakeStore()
        s.create_item("a", "a description")
        calls = {"n": 0}
        original = s.all_items

        def counted():
            calls["n"] += 1
            return original()

        s.all_items = counted
        return s, calls

    def test_execute_then_counts_on_one_instance_scans_once(self):
        s, calls = self._counting_store()
        uc = BacklogUseCase(s, None)
        uc.execute(BacklogInput())
        uc.counts()
        self.assertEqual(calls["n"], 1)

    def test_counts_then_execute_on_one_instance_scans_once(self):
        s, calls = self._counting_store()
        uc = BacklogUseCase(s, None)
        uc.counts()
        uc.execute(BacklogInput())
        self.assertEqual(calls["n"], 1)

    def test_two_independent_instances_each_scan_once(self):
        s, calls = self._counting_store()
        BacklogUseCase(s, None).execute(BacklogInput())
        BacklogUseCase(s, None).counts()
        self.assertEqual(calls["n"], 2)

    def test_backlogged_items_does_not_call_all_nodes(self):
        s = FakeStore()
        s.create_item("a", "a description")

        def raises():
            raise AssertionError("all_nodes should not be called")

        s.all_nodes = raises
        BacklogUseCase(s, None).execute(BacklogInput())

    def test_backlogged_items_does_not_call_all_nodes_including_done(self):
        s = FakeStore()
        s.create_item("a", "a description")

        def raises():
            raise AssertionError("all_nodes_including_done should not be called")

        s.all_nodes_including_done = raises
        BacklogUseCase(s, None).execute(BacklogInput())


if __name__ == "__main__":
    unittest.main()
