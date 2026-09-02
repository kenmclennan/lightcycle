import unittest

from lightcycle.application.work.backlog import (
    BacklogCountsResponse,
    BacklogInput,
    BacklogUseCase,
    ProjectCount,
)
from tests.support.fake_store import FakeStore


class TestBacklogDefault(unittest.TestCase):
    def test_returns_backlogged_items_sorted_by_id_with_project(self):
        s = FakeStore()
        b = s.create_item("b item", "a description")
        s.add_artifact(b, "repo", "proj-b")
        a = s.create_item("a item", "a description")
        s.add_artifact(a, "repo", "proj-a")
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertEqual([r.step.id for r in resp.rows], sorted([a, b]))
        by_id = {r.step.id: r.project for r in resp.rows}
        self.assertEqual(by_id[a], "proj-a")
        self.assertEqual(by_id[b], "proj-b")

    def test_item_without_repo_artifact_has_project_none(self):
        s = FakeStore()
        s.create_item("no repo", "a description")
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertIsNone(resp.rows[0].project)


class TestBacklogProjectFilter(unittest.TestCase):
    def test_filters_to_matching_project(self):
        s = FakeStore()
        keep = s.create_item("keep", "a description")
        s.add_artifact(keep, "repo", "proj-a")
        drop = s.create_item("drop", "a description")
        s.add_artifact(drop, "repo", "proj-b")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_item_without_repo_artifact_is_excluded(self):
        s = FakeStore()
        s.create_item("no repo", "a description")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a"))
        self.assertEqual(resp.rows, [])


class TestBacklogN(unittest.TestCase):
    def test_n_limits_project_filtered_items_before_grouping(self):
        s = FakeStore()
        a = s.create_item("a", "a description")
        s.add_artifact(a, "repo", "proj-a")
        b = s.create_item("b", "a description")
        s.add_artifact(b, "repo", "proj-a")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a", n=1))
        self.assertEqual(len(resp.rows), 1)
        self.assertEqual(resp.rows[0].step.id, sorted([a, b])[0])


class TestBacklogCounts(unittest.TestCase):
    def test_mixed_projects_and_unscoped(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.add_project("org-b/proj-b")
        s.add_project("org-c/proj-c")
        a1 = s.create_item("a1", "a description")
        s.add_artifact(a1, "repo", "proj-a")
        a2 = s.create_item("a2", "a description")
        s.add_artifact(a2, "repo", "proj-a")
        b1 = s.create_item("b1", "a description")
        s.add_artifact(b1, "repo", "proj-b")
        s.create_item("no repo", "a description")
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
        item = s.create_item("item", "a description")
        s.add_artifact(item, "repo", "proj-a")
        resp = BacklogUseCase(s, None).counts()
        self.assertEqual(resp.projects, [ProjectCount(project="proj-a", count=1)])

    def test_project_value_round_trips_into_execute_filter(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.add_project("org-b/proj-b")
        a1 = s.create_item("a1", "a description")
        s.add_artifact(a1, "repo", "proj-a")
        a2 = s.create_item("a2", "a description")
        s.add_artifact(a2, "repo", "proj-a")
        b1 = s.create_item("b1", "a description")
        s.add_artifact(b1, "repo", "proj-b")
        uc = BacklogUseCase(s, None)
        counts = uc.counts()
        for p in counts.projects:
            resp = uc.execute(BacklogInput(project=p.project))
            self.assertEqual(len(resp.rows), p.count)

    def test_total_includes_items_matching_no_registered_project(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.add_project("org-b/proj-b")
        a1 = s.create_item("a1", "a description")
        s.add_artifact(a1, "repo", "proj-a")
        a2 = s.create_item("a2", "a description")
        s.add_artifact(a2, "repo", "proj-a")
        b1 = s.create_item("b1", "a description")
        s.add_artifact(b1, "repo", "proj-b")
        s.create_item("no repo", "a description")
        typo = s.create_item("typo", "a description")
        s.add_artifact(typo, "repo", "typo-project")
        resp = BacklogUseCase(s, None).counts()
        self.assertEqual(resp.total, 5)
        bucketed = sum(p.count for p in resp.projects) + resp.unscoped
        self.assertGreater(resp.total, bucketed)

    def test_empty_store_returns_empty_counts(self):
        s = FakeStore()
        resp = BacklogUseCase(s, None).counts()
        self.assertEqual(resp, BacklogCountsResponse(projects=[], unscoped=0, total=0))

    def test_slash_qualified_repo_is_counted_and_matched_by_its_registered_project(self):
        s = FakeStore()
        s.add_project("org/proj")
        item = s.create_item("item", "a description")
        s.add_artifact(item, "repo", "org/proj")
        resp = BacklogUseCase(s, None).counts()
        self.assertEqual(resp.projects, [ProjectCount(project="proj", count=1)])
        filtered = BacklogUseCase(s, None).execute(BacklogInput(project="proj"))
        self.assertEqual([r.step.id for r in filtered.rows], [item])


class TestBacklogUseCaseMemoization(unittest.TestCase):
    def _counting_store(self):
        s = FakeStore()
        s.create_item("a", "a description")
        calls = {"n": 0}
        original = s.all_nodes

        def counted():
            calls["n"] += 1
            return original()

        s.all_nodes = counted
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


if __name__ == "__main__":
    unittest.main()
