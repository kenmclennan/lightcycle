import unittest

from lightcycle.application.work.done import (
    DoneCountsResponse,
    DoneInput,
    DoneUseCase,
)
from lightcycle.application.work.project_counts import ProjectCount
from tests.support.fake_store import FakeStore


class TestDoneDefault(unittest.TestCase):
    def test_returns_closed_items_with_project(self):
        s = FakeStore()
        b = s.create_item("b item", "a description")
        s.add_artifact(b, "repo", "proj-b")
        s.complete_node(b, "merged")
        a = s.create_item("a item", "a description")
        s.add_artifact(a, "repo", "proj-a")
        s.complete_node(a, "merged")
        resp = DoneUseCase(s).execute(DoneInput())
        by_id = {r.step.id: r.project for r in resp.rows}
        self.assertEqual(by_id[a], "proj-a")
        self.assertEqual(by_id[b], "proj-b")

    def test_open_items_are_excluded(self):
        s = FakeStore()
        closed = s.create_item("closed item", "a description")
        s.complete_node(closed, "merged")
        s.create_item("open item", "a description")
        resp = DoneUseCase(s).execute(DoneInput())
        self.assertEqual([r.step.id for r in resp.rows], [closed])

    def test_item_without_repo_artifact_has_project_none(self):
        s = FakeStore()
        item = s.create_item("no repo", "a description")
        s.complete_node(item, "merged")
        resp = DoneUseCase(s).execute(DoneInput())
        self.assertIsNone(resp.rows[0].project)


class TestDoneProjectFilter(unittest.TestCase):
    def test_filters_to_matching_project(self):
        s = FakeStore()
        keep = s.create_item("keep", "a description")
        s.add_artifact(keep, "repo", "proj-a")
        s.complete_node(keep, "merged")
        drop = s.create_item("drop", "a description")
        s.add_artifact(drop, "repo", "proj-b")
        s.complete_node(drop, "merged")
        resp = DoneUseCase(s).execute(DoneInput(project="proj-a"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_item_without_repo_artifact_is_excluded(self):
        s = FakeStore()
        item = s.create_item("no repo", "a description")
        s.complete_node(item, "merged")
        resp = DoneUseCase(s).execute(DoneInput(project="proj-a"))
        self.assertEqual(resp.rows, [])


class TestDoneTextFilter(unittest.TestCase):
    def test_matches_by_id_substring_case_insensitive(self):
        s = FakeStore()
        keep = s.create_item("keep", "a description", id="LC-479")
        s.complete_node(keep, "merged")
        drop = s.create_item("drop", "a description", id="LC-999")
        s.complete_node(drop, "merged")
        resp = DoneUseCase(s).execute(DoneInput(text="lc-479"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_matches_by_title_substring_case_insensitive(self):
        s = FakeStore()
        keep = s.create_item("Ship the backlog", "a description")
        s.complete_node(keep, "merged")
        drop = s.create_item("unrelated title", "a description")
        s.complete_node(drop, "merged")
        resp = DoneUseCase(s).execute(DoneInput(text="BACKLOG"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_matches_by_project_substring_case_insensitive(self):
        s = FakeStore()
        keep = s.create_item("keep", "a description")
        s.add_artifact(keep, "repo", "kenmclennan/lightcycle")
        s.complete_node(keep, "merged")
        drop = s.create_item("drop", "a description")
        s.complete_node(drop, "merged")
        resp = DoneUseCase(s).execute(DoneInput(text="LIGHTCYCLE"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_mixed_matches_and_non_matches_returns_only_the_matches(self):
        s = FakeStore()
        keep_a = s.create_item("alpha widget", "a description")
        s.complete_node(keep_a, "merged")
        keep_b = s.create_item("beta thing", "a description")
        s.add_artifact(keep_b, "repo", "widget-co")
        s.complete_node(keep_b, "merged")
        drop = s.create_item("gamma unrelated", "a description")
        s.complete_node(drop, "merged")
        resp = DoneUseCase(s).execute(DoneInput(text="widget"))
        self.assertEqual(sorted(r.step.id for r in resp.rows), sorted([keep_a, keep_b]))

    def test_project_and_text_compose_to_the_intersection(self):
        s = FakeStore()
        keep = s.create_item("target item", "a description")
        s.add_artifact(keep, "repo", "proj-a")
        s.complete_node(keep, "merged")
        wrong_project = s.create_item("target item", "a description")
        s.add_artifact(wrong_project, "repo", "proj-b")
        s.complete_node(wrong_project, "merged")
        wrong_text = s.create_item("other item", "a description")
        s.add_artifact(wrong_text, "repo", "proj-a")
        s.complete_node(wrong_text, "merged")
        resp = DoneUseCase(s).execute(DoneInput(project="proj-a", text="target"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_counts_are_unaffected_by_text(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        matching = s.create_item("target item", "a description")
        s.add_artifact(matching, "repo", "proj-a")
        s.complete_node(matching, "merged")
        other = s.create_item("other item", "a description")
        s.add_artifact(other, "repo", "proj-a")
        s.complete_node(other, "merged")
        resp = DoneUseCase(s).counts()
        by_project = {p.project: p.count for p in resp.projects}
        self.assertEqual(by_project, {"proj-a": 2})


class TestDoneOrdering(unittest.TestCase):
    def test_items_come_back_newest_closed_first(self):
        s = FakeStore()
        first = s.create_item("first", "a description")
        s.complete_node(first, "merged")
        second = s.create_item("second", "a description")
        s.complete_node(second, "merged")
        third = s.create_item("third", "a description")
        s.complete_node(third, "merged")
        resp = DoneUseCase(s).execute(DoneInput())
        self.assertEqual([r.step.id for r in resp.rows], [third, second, first])

    def test_an_item_with_no_closed_at_sorts_last(self):
        s = FakeStore()
        closed = s.create_item("closed", "a description")
        s.complete_node(closed, "merged")
        no_closed_at = s.create_item("missing timestamp", "a description")
        s.complete_node(no_closed_at, "merged")
        s._records[no_closed_at]["closed_at"] = None
        resp = DoneUseCase(s).execute(DoneInput())
        self.assertEqual(resp.rows[-1].step.id, no_closed_at)

    def test_mixed_utc_offsets_sort_chronologically_not_as_raw_strings(self):
        s = FakeStore()
        earliest = s.create_item("earliest", "a description")
        s.complete_node(earliest, "merged")
        s._records[earliest]["closed_at"] = "2026-01-01T10:00:00+00:00"
        middle = s.create_item("middle", "a description")
        s.complete_node(middle, "merged")
        s._records[middle]["closed_at"] = "2026-01-01T05:00:00-12:00"
        latest = s.create_item("latest", "a description")
        s.complete_node(latest, "merged")
        s._records[latest]["closed_at"] = "2026-01-01T20:00:00+00:00"

        resp = DoneUseCase(s).execute(DoneInput())

        self.assertEqual([r.step.id for r in resp.rows], [latest, middle, earliest])

    def test_two_items_sharing_a_closed_at_break_the_tie_deterministically(self):
        from lightcycle.domain.work import node_id_key

        s = FakeStore()
        a = s.create_item("a", "a description", id="LC-1")
        s.complete_node(a, "merged")
        b = s.create_item("b", "a description", id="LC-2")
        s.complete_node(b, "merged")
        shared = s._records[a]["closed_at"]
        s._records[b]["closed_at"] = shared
        resp = DoneUseCase(s).execute(DoneInput())
        ids = [r.step.id for r in resp.rows]
        self.assertEqual(ids, sorted([a, b], key=node_id_key, reverse=True))


class TestDoneCounts(unittest.TestCase):
    def test_mixed_projects_and_unscoped(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.add_project("org-b/proj-b")
        s.add_project("org-c/proj-c")
        a1 = s.create_item("a1", "a description")
        s.add_artifact(a1, "repo", "proj-a")
        s.complete_node(a1, "merged")
        a2 = s.create_item("a2", "a description")
        s.add_artifact(a2, "repo", "proj-a")
        s.complete_node(a2, "merged")
        b1 = s.create_item("b1", "a description")
        s.add_artifact(b1, "repo", "proj-b")
        s.complete_node(b1, "merged")
        no_repo = s.create_item("no repo", "a description")
        s.complete_node(no_repo, "merged")
        resp = DoneUseCase(s).counts()
        by_project = {p.project: p.count for p in resp.projects}
        self.assertEqual(by_project, {"proj-a": 2, "proj-b": 1, "proj-c": 0})
        self.assertEqual(resp.unscoped, 1)

    def test_empty_store_returns_empty_counts(self):
        s = FakeStore()
        resp = DoneUseCase(s).counts()
        self.assertEqual(resp, DoneCountsResponse(projects=[], unscoped=0, total=0))

    def test_project_with_zero_items_still_appears(self):
        s = FakeStore()
        s.add_project("org-c/proj-c")
        resp = DoneUseCase(s).counts()
        self.assertEqual(resp.projects, [ProjectCount(project="proj-c", count=0)])

    def test_a_bare_registered_identity_is_counted_without_raising(self):
        s = FakeStore()
        s.add_project("specs")
        item = s.create_item("item", "a description")
        s.add_artifact(item, "repo", "specs")
        s.complete_node(item, "merged")
        resp = DoneUseCase(s).counts()
        self.assertEqual(resp.projects, [ProjectCount(project="specs", count=1)])

    def test_counts_does_not_call_get_item(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.add_project("org-b/proj-b")
        item = s.create_item("item", "a description")
        s.add_artifact(item, "repo", "proj-a")
        s.complete_node(item, "merged")
        calls = {"n": 0}
        original = s.get_item

        def counted(tid):
            calls["n"] += 1
            return original(tid)

        s.get_item = counted
        DoneUseCase(s).counts()
        self.assertEqual(calls["n"], 0)


if __name__ == "__main__":
    unittest.main()
