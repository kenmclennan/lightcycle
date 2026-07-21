import unittest

from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.work import Artifact, Node
from lightcycle.render import (
    node_extra, render_backlog, render_backlog_themed, render_inbox, render_queue,
    render_workflow_mermaid,
)
from tests.unit.test_flow_from_graph import GRAPH_TEXT, STEP_METAS


TITLE_CAP = 72


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
        lines = render_backlog(rows, TITLE_CAP)
        self.assertEqual(
            lines, [_flat("t1", "proj-a", "one"), _flat("t2", "proj-a", "two")]
        )

    def test_mixed_kind_shows_prefix(self):
        rows = [row(kind="todo", step=tk(id="t1", title="one")), row(kind="action", step=tk(id="t2", title="two"))]
        lines = render_backlog(rows, TITLE_CAP)
        self.assertTrue(all(l.startswith("[") for l in lines))

    def test_missing_project_renders_dash(self):
        lines = render_backlog([row(project=None, step=tk(id="t1", title="one"))], TITLE_CAP)
        self.assertEqual(lines[0], _flat("t1", "-", "one"))

    def test_description_suffix_preserved(self):
        lines = render_backlog([row(project="proj-a", step=tk(id="t1", title="one", description="deets"))], TITLE_CAP)
        self.assertTrue(lines[0].endswith("desc:deets"))

    def test_plan_suffix_preserved(self):
        node = tk(id="t1", title="one", artifacts=[Artifact(type="plan-doc", value="plans/x.md")])
        lines = render_backlog([row(project="proj-a", step=node)], TITLE_CAP)
        self.assertIn("plan:plans/x.md", lines[0])

    def test_title_over_cap_is_truncated_with_ellipsis(self):
        title = "x" * (TITLE_CAP + 20)
        lines = render_backlog([row(project="proj-a", step=tk(id="t1", title=title))], TITLE_CAP)
        self.assertIn(title[:TITLE_CAP] + "...", lines[0])
        self.assertNotIn(title, lines[0])

    def test_title_at_or_under_cap_is_untouched(self):
        title = "x" * (TITLE_CAP - 1)
        lines = render_backlog([row(project="proj-a", step=tk(id="t1", title=title))], TITLE_CAP)
        self.assertIn(title, lines[0])


class TestRenderBacklogThemed(unittest.TestCase):
    def test_theme_heading_and_indented_items(self):
        theme = tk(id="LC-99", title="theme title")
        group = _group(theme, "proj-a", [row(step=tk(id="LC-99.1", title="item one"))])
        lines = render_backlog_themed([group], TITLE_CAP)
        self.assertEqual(lines[0], "LC-99  proj-a  theme title")
        self.assertEqual(lines[1], "    LC-99.1  item one")

    def test_no_theme_group_heading(self):
        group = _group(None, None, [row(project=None, step=tk(id="LC-77", title="loose item"))])
        lines = render_backlog_themed([group], TITLE_CAP)
        self.assertEqual(lines[0], "(no theme)")
        self.assertEqual(lines[1], _flat("LC-77", "-", "loose item"))

    def test_no_theme_group_item_shows_project(self):
        group = _group(None, None, [row(project="proj-a", step=tk(id="LC-77", title="loose item"))])
        lines = render_backlog_themed([group], TITLE_CAP)
        self.assertEqual(lines[0], "(no theme)")
        self.assertEqual(lines[1], _flat("LC-77", "proj-a", "loose item"))

    def test_blank_line_between_groups(self):
        g1 = _group(tk(id="LC-1", title="t1"), "-", [row(step=tk(id="LC-1.1", title="a"))])
        g2 = _group(None, None, [row(step=tk(id="LC-2", title="b"))])
        lines = render_backlog_themed([g1, g2], TITLE_CAP)
        self.assertEqual(lines[2], "")

    def test_empty_groups_renders_no_lines(self):
        self.assertEqual(render_backlog_themed([], TITLE_CAP), [])

    def test_title_over_cap_is_truncated_with_ellipsis(self):
        title = "x" * (TITLE_CAP + 20)
        theme = tk(id="LC-99", title="theme title")
        group = _group(theme, "proj-a", [row(step=tk(id="LC-99.1", title=title))])
        lines = render_backlog_themed([group], TITLE_CAP)
        self.assertIn(title[:TITLE_CAP] + "...", lines[1])
        self.assertNotIn(title, lines[1])

    def test_title_at_or_under_cap_is_untouched(self):
        title = "x" * (TITLE_CAP - 1)
        theme = tk(id="LC-99", title="theme title")
        group = _group(theme, "proj-a", [row(step=tk(id="LC-99.1", title=title))])
        lines = render_backlog_themed([group], TITLE_CAP)
        self.assertIn(title, lines[1])


def _group(theme, project, rows):
    from lightcycle.application.work.backlog import ThemeGroup

    return ThemeGroup(theme=theme, project=project, rows=rows)


def _inbox(kind, id_, project, title, suffix=""):
    return "%-9s  %-10s  %-12s  %s" % ("[%s]" % kind, id_, project, title) + suffix


class TestRenderInbox(unittest.TestCase):
    def test_plain_row_no_suffix(self):
        r = row(kind="action", project="proj-a", step=tk(id="t1", title="one"))
        lines = render_inbox([r], TITLE_CAP)
        self.assertEqual(lines, [_inbox("action", "t1", "proj-a", "one")])

    def test_missing_project_renders_dash(self):
        r = row(kind="action", project=None, step=tk(id="t1", title="one"))
        lines = render_inbox([r], TITLE_CAP)
        self.assertEqual(lines, [_inbox("action", "t1", "-", "one")])

    def test_blocked_row_with_needs(self):
        node = tk(id="t1", title="one", needs="waiting on X")
        r = row(kind="blocked", step=node)
        lines = render_inbox([r], TITLE_CAP)
        self.assertTrue(lines[0].endswith("  needs:waiting on X"))

    def test_blocked_row_without_needs_has_no_suffix(self):
        r = row(kind="blocked", project="proj-a", step=tk(id="t1", title="one"))
        lines = render_inbox([r], TITLE_CAP)
        self.assertEqual(lines, [_inbox("blocked", "t1", "proj-a", "one")])

    def test_triage_row_with_notes(self):
        node = tk(id="t1", title="one", notes="found: missing test coverage")
        r = row(kind="triage", step=node)
        lines = render_inbox([r], TITLE_CAP)
        self.assertTrue(lines[0].endswith("  findings:found: missing test coverage"))

    def test_triage_row_multiline_notes_first_line_truncated(self):
        first_line = "x" * 80
        node = tk(id="t1", title="one", notes=first_line + "\nsecond line")
        r = row(kind="triage", step=node)
        lines = render_inbox([r], TITLE_CAP)
        self.assertTrue(lines[0].endswith("  findings:" + "x" * 60 + "..."))

    def test_action_row_with_pr_shows_pr_suffix(self):
        r = row(kind="action", step=tk(id="t1", title="one"), pr="https://example.com/pr/1")
        lines = render_inbox([r], TITLE_CAP)
        self.assertTrue(lines[0].endswith("  pr:https://example.com/pr/1"))

    def test_blocked_row_with_pr_shows_needs_not_pr(self):
        node = tk(id="t1", title="one", needs="waiting on X")
        r = row(kind="blocked", step=node, pr="https://example.com/pr/1")
        lines = render_inbox([r], TITLE_CAP)
        self.assertTrue(lines[0].endswith("  needs:waiting on X"))
        self.assertNotIn("pr:", lines[0])

    def test_kind_always_shown_even_for_single_row(self):
        lines = render_inbox([row(kind="action", step=tk(id="t1", title="one"))], TITLE_CAP)
        self.assertTrue(lines[0].startswith("[action]"))

    def test_desc_suffix_renders_after_strategy_suffix(self):
        node = tk(id="t1", title="one", needs="waiting on X", description="deets")
        r = row(kind="blocked", step=node)
        lines = render_inbox([r], TITLE_CAP)
        self.assertTrue(lines[0].endswith("  needs:waiting on X  desc:deets"))

    def test_plan_suffix_renders_after_strategy_suffix(self):
        node = tk(
            id="t1", title="one", needs="waiting on X",
            artifacts=[Artifact(type="plan-doc", value="plans/x.md")],
        )
        r = row(kind="blocked", step=node)
        lines = render_inbox([r], TITLE_CAP)
        self.assertTrue(lines[0].endswith("  needs:waiting on X  plan:plans/x.md"))

    def test_mixed_kinds_align_id_column(self):
        rows = [
            row(kind="action", project="proj-a", step=tk(id="t1", title="one")),
            row(kind="blocked", project="proj-a", step=tk(id="t2", title="two")),
        ]
        lines = render_inbox(rows, TITLE_CAP)
        id_offset = lines[0].index("t1")
        self.assertEqual(id_offset, lines[1].index("t2"))

    def test_title_over_cap_is_truncated_with_ellipsis(self):
        title = "x" * (TITLE_CAP + 20)
        r = row(kind="action", project="proj-a", step=tk(id="t1", title=title))
        lines = render_inbox([r], TITLE_CAP)
        self.assertIn(title[:TITLE_CAP] + "...", lines[0])
        self.assertNotIn(title, lines[0])

    def test_title_at_or_under_cap_is_untouched(self):
        title = "x" * (TITLE_CAP - 1)
        r = row(kind="action", project="proj-a", step=tk(id="t1", title=title))
        lines = render_inbox([r], TITLE_CAP)
        self.assertIn(title, lines[0])


class TestRenderQueue(unittest.TestCase):
    def test_short_title_passes_through(self):
        lines = render_queue([tk(id="t1", title="one", state="ready")], TITLE_CAP)
        self.assertEqual(lines, ["  %-8s %s  %s" % ("ready", "t1", "one")])

    def test_title_over_cap_is_truncated_with_ellipsis(self):
        title = "x" * (TITLE_CAP + 20)
        lines = render_queue([tk(id="t1", title=title, state="ready")], TITLE_CAP)
        self.assertIn(title[:TITLE_CAP] + "...", lines[0])
        self.assertNotIn(title, lines[0])

    def test_state_and_id_columns_preserved(self):
        lines = render_queue([tk(id="t1", title="one", state="in_progress")], TITLE_CAP)
        self.assertIn("in_progress", lines[0])
        self.assertIn("t1", lines[0])


PHASE_GRAPH_TEXT = """
entry: build

nodes:
  build   coder
  review  reviewer
  ship    shipper

edges:
  build   done    review
  review  done    ship
  review  reject  build
  ship    done    done-terminal

phase:
  build   code
  review  code
  ship    test
"""

PHASE_STEP_METAS = {
    "coder": {"model": "sonnet"},
    "reviewer": {"model": "sonnet"},
    "shipper": {"model": "sonnet"},
}


class TestRenderWorkflowMermaid(unittest.TestCase):
    def setUp(self):
        self.graph = parse_graph(GRAPH_TEXT)
        self.flow = Flow.from_graph(self.graph, STEP_METAS)
        self.lines = render_workflow_mermaid(self.graph, self.flow)

    def test_starts_with_flowchart_header(self):
        self.assertEqual(self.lines[0], "flowchart TD")

    def test_every_stage_declared_with_expected_shape(self):
        self.assertIn('build["build"]', self.lines)
        self.assertIn('review["review"]', self.lines)
        self.assertIn('audit["audit"]', self.lines)
        self.assertIn('open_pr["open-pr"]', self.lines)
        self.assertIn('watch_pr["watch-pr"]', self.lines)
        self.assertIn('handle_feedback["handle-feedback"]', self.lines)
        self.assertIn('ready_merge("ready-merge")', self.lines)
        self.assertIn('cleanup("cleanup")', self.lines)
        self.assertIn('review_findings("review-findings")', self.lines)
        self.assertIn('review_ci("review-ci")', self.lines)
        self.assertIn('conflict_review(["conflict-review"])', self.lines)

    def test_class_lines_group_by_kind(self):
        self.assertIn(
            "class audit,build,handle_feedback,open_pr,review,watch_pr agent", self.lines
        )
        self.assertIn(
            "class cleanup,ready_merge,review_ci,review_findings human", self.lines
        )
        self.assertIn("class conflict_review terminal", self.lines)

    def test_pr_merge_pair_rendered_only_as_dashed_hook_edge(self):
        self.assertIn("ready_merge -.->|pr_merge: merged| cleanup", self.lines)
        self.assertNotIn("ready_merge -->|merged| cleanup", self.lines)

    def test_pr_conflict_base_outcome_with_no_edge_produces_nothing(self):
        for line in self.lines:
            self.assertNotIn("conflicted", line)

    def test_pr_conflict_cap_and_plain_edge_both_render(self):
        self.assertIn(
            "ready_merge -.->|pr_conflict_cap x3: gave-up| conflict_review", self.lines
        )
        self.assertIn("ready_merge -->|gave-up| conflict_review", self.lines)

    def test_pr_feedback_edge_has_no_outcome_in_label(self):
        self.assertIn("ready_merge -.->|pr_feedback| handle_feedback", self.lines)

    def test_ci_failed_cap_edge_carries_count_and_outcome(self):
        self.assertIn("watch_pr -.->|ci_failed_cap x3: ci-failed| review_ci", self.lines)

    def test_no_phases_means_no_subgraphs(self):
        for line in self.lines:
            self.assertNotIn("subgraph", line)


class TestRenderWorkflowMermaidPhases(unittest.TestCase):
    def setUp(self):
        self.graph = parse_graph(PHASE_GRAPH_TEXT)
        self.flow = Flow.from_graph(self.graph, PHASE_STEP_METAS)
        self.lines = render_workflow_mermaid(self.graph, self.flow)

    def test_phased_stages_grouped_into_subgraphs_sorted(self):
        code_start = self.lines.index('subgraph phase_code["code"]')
        test_start = self.lines.index('subgraph phase_test["test"]')
        self.assertLess(code_start, test_start)
        code_end = self.lines.index("end", code_start)
        test_end = self.lines.index("end", test_start)
        self.assertIn('  build["build"]', self.lines[code_start:code_end])
        self.assertIn('  review["review"]', self.lines[code_start:code_end])
        self.assertIn('  ship["ship"]', self.lines[test_start:test_end])

    def test_unphased_terminal_declared_outside_every_subgraph(self):
        terminal_line = 'done_terminal(["done-terminal"])'
        self.assertIn(terminal_line, self.lines)
        test_end = self.lines.index("end", self.lines.index('subgraph phase_test["test"]'))
        self.assertGreater(self.lines.index(terminal_line), test_end)


if __name__ == "__main__":
    unittest.main()
