import datetime
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
        b = s.create_item("b item", "a description", project="proj-b")
        s.complete_node(b, "merged")
        a = s.create_item("a item", "a description", project="proj-a")
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

    def test_item_without_project_has_project_none(self):
        s = FakeStore()
        item = s.create_item("no project", "a description")
        s.complete_node(item, "merged")
        resp = DoneUseCase(s).execute(DoneInput())
        self.assertIsNone(resp.rows[0].project)

    def test_row_shows_project_and_repo_independently(self):
        s = FakeStore()
        item = s.create_item("item", "a description", project="proj-a")
        s.add_artifact(item, "repo", "org/repo-a")
        s.complete_node(item, "merged")
        resp = DoneUseCase(s).execute(DoneInput())
        self.assertEqual(resp.rows[0].project, "proj-a")
        self.assertEqual(resp.rows[0].repo, "org/repo-a")

    def test_row_with_repo_but_no_project_does_not_leak_into_project(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.add_artifact(item, "repo", "org/repo-a")
        s.complete_node(item, "merged")
        resp = DoneUseCase(s).execute(DoneInput())
        self.assertIsNone(resp.rows[0].project)
        self.assertEqual(resp.rows[0].repo, "org/repo-a")


class TestDoneProjectFilter(unittest.TestCase):
    def test_filters_to_matching_project(self):
        s = FakeStore()
        keep = s.create_item("keep", "a description", project="proj-a")
        s.complete_node(keep, "merged")
        drop = s.create_item("drop", "a description", project="proj-b")
        s.complete_node(drop, "merged")
        resp = DoneUseCase(s).execute(DoneInput(project="proj-a"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_item_without_project_is_excluded(self):
        s = FakeStore()
        item = s.create_item("no project", "a description")
        s.complete_node(item, "merged")
        resp = DoneUseCase(s).execute(DoneInput(project="proj-a"))
        self.assertEqual(resp.rows, [])

    def test_item_whose_project_matches_but_repo_differs_is_included(self):
        s = FakeStore()
        item = s.create_item("item", "a description", project="proj-a")
        s.add_artifact(item, "repo", "org/proj-b")
        s.complete_node(item, "merged")
        resp = DoneUseCase(s).execute(DoneInput(project="proj-a"))
        self.assertEqual([r.step.id for r in resp.rows], [item])

    def test_item_whose_repo_matches_but_project_differs_is_excluded(self):
        s = FakeStore()
        item = s.create_item("item", "a description", project="proj-b")
        s.add_artifact(item, "repo", "org/proj-a")
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
        keep = s.create_item("keep", "a description", project="kenmclennan/lightcycle")
        s.complete_node(keep, "merged")
        drop = s.create_item("drop", "a description")
        s.complete_node(drop, "merged")
        resp = DoneUseCase(s).execute(DoneInput(text="LIGHTCYCLE"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_mixed_matches_and_non_matches_returns_only_the_matches(self):
        s = FakeStore()
        keep_a = s.create_item("alpha widget", "a description")
        s.complete_node(keep_a, "merged")
        keep_b = s.create_item("beta thing", "a description", project="widget-co")
        s.complete_node(keep_b, "merged")
        drop = s.create_item("gamma unrelated", "a description")
        s.complete_node(drop, "merged")
        resp = DoneUseCase(s).execute(DoneInput(text="widget"))
        self.assertEqual(sorted(r.step.id for r in resp.rows), sorted([keep_a, keep_b]))

    def test_project_and_text_compose_to_the_intersection(self):
        s = FakeStore()
        keep = s.create_item("target item", "a description", project="proj-a")
        s.complete_node(keep, "merged")
        wrong_project = s.create_item("target item", "a description", project="proj-b")
        s.complete_node(wrong_project, "merged")
        wrong_text = s.create_item("other item", "a description", project="proj-a")
        s.complete_node(wrong_text, "merged")
        resp = DoneUseCase(s).execute(DoneInput(project="proj-a", text="target"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_counts_are_unaffected_by_text(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        matching = s.create_item("target item", "a description", project="proj-a")
        s.complete_node(matching, "merged")
        other = s.create_item("other item", "a description", project="proj-a")
        s.complete_node(other, "merged")
        resp = DoneUseCase(s).counts()
        by_project = {p.project: p.count for p in resp.projects}
        self.assertEqual(by_project, {"proj-a": 2})


class TestDoneDayFilter(unittest.TestCase):
    def test_matches_a_specific_day_exactly(self):
        s = FakeStore()
        keep = s.create_item("keep", "a description")
        s.complete_node(keep, "merged")
        s._records[keep]["closed_at"] = "2026-01-01T10:00:00+00:00"
        drop = s.create_item("drop", "a description")
        s.complete_node(drop, "merged")
        s._records[drop]["closed_at"] = "2026-01-02T10:00:00+00:00"
        resp = DoneUseCase(s).execute(DoneInput(day=datetime.date(2026, 1, 1)))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_a_day_with_zero_matches_returns_nothing(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.complete_node(item, "merged")
        s._records[item]["closed_at"] = "2026-01-01T10:00:00+00:00"
        resp = DoneUseCase(s).execute(DoneInput(day=datetime.date(2026, 1, 5)))
        self.assertEqual(resp.rows, [])

    def test_none_returns_everything_unchanged(self):
        s = FakeStore()
        a = s.create_item("a", "a description")
        s.complete_node(a, "merged")
        s._records[a]["closed_at"] = "2026-01-01T10:00:00+00:00"
        b = s.create_item("b", "a description")
        s.complete_node(b, "merged")
        s._records[b]["closed_at"] = "2026-01-02T10:00:00+00:00"
        resp = DoneUseCase(s).execute(DoneInput(day=None))
        self.assertEqual(sorted(r.step.id for r in resp.rows), sorted([a, b]))

    def test_an_item_with_no_closed_at_never_matches_a_specific_day_but_appears_under_none(self):
        s = FakeStore()
        item = s.create_item("no closed at", "a description")
        s.complete_node(item, "merged")
        s._records[item]["closed_at"] = None
        specific = DoneUseCase(s).execute(DoneInput(day=datetime.date(2026, 1, 1)))
        self.assertEqual(specific.rows, [])
        unfiltered = DoneUseCase(s).execute(DoneInput(day=None))
        self.assertEqual([r.step.id for r in unfiltered.rows], [item])

    def test_offsets_bucket_by_their_own_recorded_local_calendar_day(self):
        s = FakeStore()
        early_offset = s.create_item("early offset", "a description")
        s.complete_node(early_offset, "merged")
        s._records[early_offset]["closed_at"] = "2026-01-01T23:30:00-05:00"
        late_offset = s.create_item("late offset", "a description")
        s.complete_node(late_offset, "merged")
        s._records[late_offset]["closed_at"] = "2026-01-02T02:30:00+00:00"

        jan_1 = DoneUseCase(s).execute(DoneInput(day=datetime.date(2026, 1, 1)))
        jan_2 = DoneUseCase(s).execute(DoneInput(day=datetime.date(2026, 1, 2)))

        self.assertEqual([r.step.id for r in jan_1.rows], [early_offset])
        self.assertEqual([r.step.id for r in jan_2.rows], [late_offset])


class TestDoneDayCounts(unittest.TestCase):
    def test_buckets_correctly_across_multiple_days(self):
        s = FakeStore()
        a1 = s.create_item("a1", "a description")
        s.complete_node(a1, "merged")
        s._records[a1]["closed_at"] = "2026-01-01T10:00:00+00:00"
        a2 = s.create_item("a2", "a description")
        s.complete_node(a2, "merged")
        s._records[a2]["closed_at"] = "2026-01-01T12:00:00+00:00"
        b1 = s.create_item("b1", "a description")
        s.complete_node(b1, "merged")
        s._records[b1]["closed_at"] = "2026-01-02T10:00:00+00:00"
        by_day = {dc.day: dc.count for dc in DoneUseCase(s).day_counts()}
        self.assertEqual(by_day, {datetime.date(2026, 1, 1): 2, datetime.date(2026, 1, 2): 1})

    def test_items_with_no_closed_at_are_excluded_from_every_bucket_but_still_in_total(self):
        s = FakeStore()
        dated = s.create_item("dated", "a description")
        s.complete_node(dated, "merged")
        s._records[dated]["closed_at"] = "2026-01-01T10:00:00+00:00"
        undated = s.create_item("undated", "a description")
        s.complete_node(undated, "merged")
        s._records[undated]["closed_at"] = None
        uc = DoneUseCase(s)
        self.assertEqual(sum(dc.count for dc in uc.day_counts()), 1)
        self.assertEqual(uc.counts().total, 2)

    def test_ordering_is_most_recent_day_first(self):
        s = FakeStore()
        old = s.create_item("old", "a description")
        s.complete_node(old, "merged")
        s._records[old]["closed_at"] = "2026-01-01T10:00:00+00:00"
        new = s.create_item("new", "a description")
        s.complete_node(new, "merged")
        s._records[new]["closed_at"] = "2026-01-03T10:00:00+00:00"
        middle = s.create_item("middle", "a description")
        s.complete_node(middle, "merged")
        s._records[middle]["closed_at"] = "2026-01-02T10:00:00+00:00"
        self.assertEqual(
            [dc.day for dc in DoneUseCase(s).day_counts()],
            [datetime.date(2026, 1, 3), datetime.date(2026, 1, 2), datetime.date(2026, 1, 1)],
        )

    def test_empty_store_returns_empty_list(self):
        s = FakeStore()
        self.assertEqual(DoneUseCase(s).day_counts(), [])

    def test_execute_day_counts_and_counts_together_on_one_instance_scans_once(self):
        s = FakeStore()
        item = s.create_item("a", "a description")
        s.complete_node(item, "merged")
        calls = {"n": 0}
        original = s.all_items_including_done

        def counted():
            calls["n"] += 1
            return original()

        s.all_items_including_done = counted
        uc = DoneUseCase(s)
        uc.execute(DoneInput())
        uc.day_counts()
        uc.counts()
        self.assertEqual(calls["n"], 1)


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
        a1 = s.create_item("a1", "a description", project="proj-a")
        s.complete_node(a1, "merged")
        a2 = s.create_item("a2", "a description", project="proj-a")
        s.complete_node(a2, "merged")
        b1 = s.create_item("b1", "a description", project="proj-b")
        s.complete_node(b1, "merged")
        no_project = s.create_item("no project", "a description")
        s.complete_node(no_project, "merged")
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
        item = s.create_item("item", "a description", project="specs")
        s.complete_node(item, "merged")
        resp = DoneUseCase(s).counts()
        self.assertEqual(resp.projects, [ProjectCount(project="specs", count=1)])

    def test_counts_does_not_call_get_item(self):
        s = FakeStore()
        s.add_project("org-a/proj-a")
        s.add_project("org-b/proj-b")
        item = s.create_item("item", "a description", project="proj-a")
        s.complete_node(item, "merged")
        calls = {"n": 0}
        original = s.get_item

        def counted(tid):
            calls["n"] += 1
            return original(tid)

        s.get_item = counted
        DoneUseCase(s).counts()
        self.assertEqual(calls["n"], 0)

    def test_closed_items_does_not_call_all_nodes_including_done(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.complete_node(item, "merged")

        def raises():
            raise AssertionError("all_nodes_including_done should not be called")

        s.all_nodes_including_done = raises
        DoneUseCase(s).execute(DoneInput())

    def test_closed_items_does_not_call_all_nodes(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.complete_node(item, "merged")

        def raises():
            raise AssertionError("all_nodes should not be called")

        s.all_nodes = raises
        DoneUseCase(s).execute(DoneInput())


class TestDoneUseCaseMemoization(unittest.TestCase):
    def _counting_store(self):
        s = FakeStore()
        s.create_item("a", "a description")
        calls = {"n": 0}
        original = s.all_items_including_done

        def counted():
            calls["n"] += 1
            return original()

        s.all_items_including_done = counted
        return s, calls

    def test_execute_then_counts_on_one_instance_scans_once(self):
        s, calls = self._counting_store()
        uc = DoneUseCase(s)
        uc.execute(DoneInput())
        uc.counts()
        self.assertEqual(calls["n"], 1)

    def test_counts_then_execute_on_one_instance_scans_once(self):
        s, calls = self._counting_store()
        uc = DoneUseCase(s)
        uc.counts()
        uc.execute(DoneInput())
        self.assertEqual(calls["n"], 1)

    def test_two_independent_instances_each_scan_once(self):
        s, calls = self._counting_store()
        DoneUseCase(s).execute(DoneInput())
        DoneUseCase(s).counts()
        self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
