import unittest

from lightcycle.application.work.backlog import BacklogInput, BacklogUseCase
from tests.support.fake_store import FakeStore


class TestBacklogDefault(unittest.TestCase):
    def test_returns_backlogged_items_sorted_by_id_with_project(self):
        s = FakeStore()
        b = s.create_item("b item")
        s.add_artifact(b, "repo", "proj-b")
        a = s.create_item("a item")
        s.add_artifact(a, "repo", "proj-a")
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertEqual([r.step.id for r in resp.rows], sorted([a, b]))
        by_id = {r.step.id: r.project for r in resp.rows}
        self.assertEqual(by_id[a], "proj-a")
        self.assertEqual(by_id[b], "proj-b")

    def test_item_without_repo_artifact_has_project_none(self):
        s = FakeStore()
        s.create_item("no repo")
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertIsNone(resp.rows[0].project)

    def test_groups_is_none_by_default(self):
        s = FakeStore()
        s.create_item("solo")
        resp = BacklogUseCase(s, None).execute(BacklogInput())
        self.assertIsNone(resp.groups)


class TestBacklogProjectFilter(unittest.TestCase):
    def test_filters_to_matching_project(self):
        s = FakeStore()
        keep = s.create_item("keep")
        s.add_artifact(keep, "repo", "proj-a")
        drop = s.create_item("drop")
        s.add_artifact(drop, "repo", "proj-b")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a"))
        self.assertEqual([r.step.id for r in resp.rows], [keep])

    def test_item_without_repo_artifact_is_excluded(self):
        s = FakeStore()
        s.create_item("no repo")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a"))
        self.assertEqual(resp.rows, [])


class TestBacklogThemes(unittest.TestCase):
    def test_items_grouped_under_their_theme_sorted_by_item_id(self):
        s = FakeStore()
        theme = s.create_theme("theme title")
        s.add_artifact(theme, "repo", "theme-proj")
        i2 = s.create_item("item two", theme=theme)
        i1 = s.create_item("item one", theme=theme)
        resp = BacklogUseCase(s, None).execute(BacklogInput(themes=True))
        self.assertEqual(len(resp.groups), 1)
        group = resp.groups[0]
        self.assertEqual(group.theme.id, theme)
        self.assertEqual(group.project, "theme-proj")
        self.assertEqual([r.step.id for r in group.rows], sorted([i1, i2]))

    def test_items_without_theme_land_in_trailing_no_theme_group(self):
        s = FakeStore()
        loose = s.create_item("loose")
        resp = BacklogUseCase(s, None).execute(BacklogInput(themes=True))
        self.assertEqual(len(resp.groups), 1)
        self.assertIsNone(resp.groups[0].theme)
        self.assertEqual([r.step.id for r in resp.groups[0].rows], [loose])

    def test_no_theme_group_is_always_last(self):
        s = FakeStore()
        theme = s.create_theme("theme title")
        s.create_item("in theme", theme=theme)
        s.create_item("loose")
        resp = BacklogUseCase(s, None).execute(BacklogInput(themes=True))
        self.assertIsNone(resp.groups[-1].theme)

    def test_theme_with_zero_matching_items_produces_no_group(self):
        s = FakeStore()
        s.create_theme("empty theme")
        resp = BacklogUseCase(s, None).execute(BacklogInput(themes=True))
        self.assertEqual(resp.groups, [])

    def test_closed_theme_still_resolved_via_get_node(self):
        s = FakeStore()
        theme = s.create_theme("closing theme")
        s.add_artifact(theme, "repo", "theme-proj")
        item = s.create_item("still open item", theme=theme)
        s.close(theme, "closed early")
        resp = BacklogUseCase(s, None).execute(BacklogInput(themes=True))
        self.assertEqual(len(resp.groups), 1)
        self.assertEqual(resp.groups[0].theme.id, theme)
        self.assertEqual(resp.groups[0].project, "theme-proj")
        self.assertEqual([r.step.id for r in resp.groups[0].rows], [item])


class TestBacklogProjectAndThemesComposed(unittest.TestCase):
    def test_project_filter_applies_before_grouping(self):
        s = FakeStore()
        theme = s.create_theme("theme title")
        keep = s.create_item("keep", theme=theme)
        s.add_artifact(keep, "repo", "proj-a")
        drop = s.create_item("drop", theme=theme)
        s.add_artifact(drop, "repo", "proj-b")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a", themes=True))
        self.assertEqual(len(resp.groups), 1)
        self.assertEqual([r.step.id for r in resp.groups[0].rows], [keep])

    def test_theme_omitted_when_no_items_pass_project_filter(self):
        s = FakeStore()
        theme = s.create_theme("theme title")
        s.add_artifact(theme, "repo", "proj-a")
        drop = s.create_item("drop", theme=theme)
        s.add_artifact(drop, "repo", "proj-b")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a", themes=True))
        self.assertEqual(resp.groups, [])


class TestBacklogN(unittest.TestCase):
    def test_n_limits_project_filtered_items_before_grouping(self):
        s = FakeStore()
        a = s.create_item("a")
        s.add_artifact(a, "repo", "proj-a")
        b = s.create_item("b")
        s.add_artifact(b, "repo", "proj-a")
        resp = BacklogUseCase(s, None).execute(BacklogInput(project="proj-a", n=1))
        self.assertEqual(len(resp.rows), 1)
        self.assertEqual(resp.rows[0].step.id, sorted([a, b])[0])


if __name__ == "__main__":
    unittest.main()
