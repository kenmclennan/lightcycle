import unittest

from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.domain.work import Artifact, Node
from lightcycle.render import node_extra, render_backlog, render_backlog_themed


def tk(**kw):
    kw.setdefault("id", "t1")
    kw.setdefault("title", "a title")
    return Node(**kw)


def row(**kw):
    kw.setdefault("kind", "todo")
    kw.setdefault("outcomes", [])
    kw.setdefault("step", tk())
    return HumanNodeRow(**kw)


class TestNodeExtra(unittest.TestCase):
    def test_no_plan_no_description(self):
        self.assertEqual(node_extra(tk()), "")

    def test_plan_suffix(self):
        node = tk(artifacts=[Artifact(type="plan-doc", value="plans/x.md")])
        self.assertEqual(node_extra(node), "  plan:plans/x.md")

    def test_description_suffix_when_shown(self):
        node = tk(description="short desc")
        self.assertEqual(node_extra(node, show_description=True), "  desc:short desc")

    def test_description_not_shown_by_default(self):
        node = tk(description="short desc")
        self.assertEqual(node_extra(node), "")

    def test_description_truncated_at_60_chars(self):
        node = tk(description="x" * 80)
        extra = node_extra(node, show_description=True)
        self.assertEqual(extra, "  desc:" + "x" * 60 + "...")

    def test_plan_and_description_both(self):
        node = tk(
            artifacts=[Artifact(type="plan-doc", value="plans/x.md")],
            description="short desc",
        )
        self.assertEqual(node_extra(node, show_description=True), "  plan:plans/x.md  desc:short desc")


def _flat(id_, project, title, extra=""):
    return "%-10s  %-12s  %s%s" % (id_, project, title, extra)


class TestRenderBacklog(unittest.TestCase):
    def test_single_kind_no_prefix(self):
        rows = [
            row(project="proj-a", step=tk(id="t1", title="one")),
            row(project="proj-a", step=tk(id="t2", title="two")),
        ]
        lines = render_backlog(rows)
        self.assertEqual(
            lines, [_flat("t1", "proj-a", "one"), _flat("t2", "proj-a", "two")]
        )

    def test_mixed_kind_shows_prefix(self):
        rows = [row(kind="todo", step=tk(id="t1", title="one")), row(kind="action", step=tk(id="t2", title="two"))]
        lines = render_backlog(rows)
        self.assertTrue(all(l.startswith("[") for l in lines))

    def test_missing_project_renders_dash(self):
        lines = render_backlog([row(project=None, step=tk(id="t1", title="one"))])
        self.assertEqual(lines[0], _flat("t1", "-", "one"))

    def test_description_suffix_preserved(self):
        lines = render_backlog([row(project="proj-a", step=tk(id="t1", title="one", description="deets"))])
        self.assertTrue(lines[0].endswith("desc:deets"))

    def test_plan_suffix_preserved(self):
        node = tk(id="t1", title="one", artifacts=[Artifact(type="plan-doc", value="plans/x.md")])
        lines = render_backlog([row(project="proj-a", step=node)])
        self.assertIn("plan:plans/x.md", lines[0])


class TestRenderBacklogThemed(unittest.TestCase):
    def test_theme_heading_and_indented_items(self):
        theme = tk(id="LC-99", title="theme title")
        group = _group(theme, "proj-a", [row(step=tk(id="LC-99.1", title="item one"))])
        lines = render_backlog_themed([group])
        self.assertEqual(lines[0], "LC-99  proj-a  theme title")
        self.assertEqual(lines[1], "    LC-99.1  item one")

    def test_no_theme_group_heading(self):
        group = _group(None, None, [row(project=None, step=tk(id="LC-77", title="loose item"))])
        lines = render_backlog_themed([group])
        self.assertEqual(lines[0], "(no theme)")
        self.assertEqual(lines[1], _flat("LC-77", "-", "loose item"))

    def test_no_theme_group_item_shows_project(self):
        group = _group(None, None, [row(project="proj-a", step=tk(id="LC-77", title="loose item"))])
        lines = render_backlog_themed([group])
        self.assertEqual(lines[0], "(no theme)")
        self.assertEqual(lines[1], _flat("LC-77", "proj-a", "loose item"))

    def test_blank_line_between_groups(self):
        g1 = _group(tk(id="LC-1", title="t1"), "-", [row(step=tk(id="LC-1.1", title="a"))])
        g2 = _group(None, None, [row(step=tk(id="LC-2", title="b"))])
        lines = render_backlog_themed([g1, g2])
        self.assertEqual(lines[2], "")

    def test_empty_groups_renders_no_lines(self):
        self.assertEqual(render_backlog_themed([]), [])


def _group(theme, project, rows):
    from lightcycle.application.work.backlog import ThemeGroup

    return ThemeGroup(theme=theme, project=project, rows=rows)


if __name__ == "__main__":
    unittest.main()
