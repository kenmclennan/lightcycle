import unittest

from the_grid.domain.flow.graph import parse_graph


class TestWorkflowGraphParsing(unittest.TestCase):
    def test_parses_entry_and_an_edge(self):
        graph = parse_graph(
            "# Standard\n"
            "\n"
            "entry: build\n"
            "\n"
            "edges:\n"
            "  build  done  review\n"
        )
        self.assertEqual(graph.entry, "build")
        self.assertEqual(graph.target("build", "done"), "review")

    def test_nodes_map_a_stage_to_its_step_file(self):
        graph = parse_graph(
            "entry: build\n"
            "\n"
            "nodes:\n"
            "  build   coder\n"
            "  review  reviewer\n"
        )
        self.assertEqual(graph.file_for("build"), "coder")
        self.assertEqual(graph.file_for("review"), "reviewer")

    def test_file_for_defaults_to_the_stage_name_when_unmapped(self):
        graph = parse_graph("entry: build\n\nnodes:\n  build  coder\n")
        self.assertEqual(graph.file_for("open-pr"), "open-pr")

    def test_hooks_carry_a_stage_and_an_optional_value(self):
        graph = parse_graph(
            "entry: build\n"
            "\n"
            "hooks:\n"
            "  pr_merge       ready-merge  merged\n"
            "  pr_conflict_cap  ready-merge  3\n"
            "  epic_close     audit\n"
        )
        self.assertEqual(graph.hook_stage("pr_merge"), "ready-merge")
        self.assertEqual(graph.hook_value("pr_merge"), "merged")
        self.assertEqual(graph.hook_value("pr_conflict_cap"), "3")
        self.assertEqual(graph.hook_stage("epic_close"), "audit")
        self.assertIsNone(graph.hook_value("epic_close"))
        self.assertIsNone(graph.hook_stage("pr_close"))

    def test_parses_signals_by_stage(self):
        graph = parse_graph(
            "entry: build\n"
            "\n"
            "signals:\n"
            "  review   review_rounds  rejected\n"
            "  open-pr  conflicts      ~conflict\n"
        )
        self.assertEqual(graph.signals["review"], {"review_rounds": "rejected"})
        self.assertEqual(graph.signals["open-pr"], {"conflicts": "~conflict"})

    def test_ignores_prose_and_blank_lines(self):
        graph = parse_graph(
            "# Standard - spec to merge\n"
            "\n"
            "Some documentation prose that is not a section.\n"
            "\n"
            "entry: build\n"
            "\n"
            "edges:\n"
            "  build  done  review\n"
        )
        self.assertEqual(graph.entry, "build")
        self.assertEqual(graph.target("build", "done"), "review")
        self.assertEqual(graph.file_for("build"), "build")
