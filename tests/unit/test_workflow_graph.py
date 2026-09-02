import unittest

from lightcycle.domain.flow.graph import parse_graph


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
            "  deploy_green    audit\n"
        )
        self.assertEqual(graph.hook_occurrences("pr_merge"), [["ready-merge", "merged"]])
        self.assertEqual(graph.hook_occurrences("pr_conflict_cap"), [["ready-merge", "3"]])
        self.assertEqual(graph.hook_occurrences("deploy_green"), [["audit"]])
        self.assertEqual(graph.hook_occurrences("pr_close"), [])

    def test_a_hook_can_fire_on_multiple_stages(self):
        graph = parse_graph(
            "entry: spec-writer\n"
            "\n"
            "hooks:\n"
            "  pr_merge  spec-await-merge  spec-merged\n"
            "  pr_merge  code-await-merge  merged\n"
        )
        self.assertEqual(
            graph.hook_occurrences("pr_merge"),
            [["spec-await-merge", "spec-merged"], ["code-await-merge", "merged"]],
        )

    def test_hook_extra_carries_a_third_token(self):
        graph = parse_graph(
            "entry: build\n"
            "\n"
            "hooks:\n"
            "  ci_failed_cap  watch-ci  3  review-ci\n"
            "  pr_merge       ready-merge  merged\n"
        )
        self.assertEqual(graph.hook_occurrences("ci_failed_cap"),
                         [["watch-ci", "3", "review-ci"]])

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

    def test_edge_with_no_target_declares_a_terminal_outcome(self):
        graph = parse_graph(
            "entry: build\n"
            "\n"
            "edges:\n"
            "  build  done  review\n"
            "  build  clean\n"
        )
        self.assertIsNone(graph.target("build", "clean"))
        self.assertIn("clean", graph.edges["build"])

    def test_parses_requires(self):
        graph = parse_graph(
            "entry: build\n"
            "\n"
            "requires: repo\n"
            "\n"
            "edges:\n"
            "  build  done  review\n"
        )
        self.assertEqual(graph.requires, {"repo"})

    def test_requires_defaults_to_empty_when_absent(self):
        graph = parse_graph("entry: build\n\nedges:\n  build  done  review\n")
        self.assertEqual(graph.requires, frozenset())

    def test_parses_workspace(self):
        graph = parse_graph(
            "entry: build\n"
            "\n"
            "workspace: specs\n"
            "\n"
            "edges:\n"
            "  build  done  review\n"
        )
        self.assertEqual(graph.workspace, "specs")

    def test_workspace_defaults_to_project_when_absent(self):
        graph = parse_graph("entry: build\n\nedges:\n  build  done  review\n")
        self.assertEqual(graph.workspace, "project")

    def test_scalar_workspace_applies_to_every_stage(self):
        graph = parse_graph("entry: build\n\nworkspace: specs\n\nedges:\n  build  done  review\n")
        self.assertEqual(graph.workspace_for("build"), "specs")
        self.assertEqual(graph.workspace_for("anything"), "specs")

    def test_workspace_block_maps_per_stage_with_project_default(self):
        graph = parse_graph(
            "entry: spec-writer\n\n"
            "workspace:\n"
            "  spec-writer       specs\n"
            "  spec-await-merge  specs\n\n"
            "edges:\n  spec-writer  done  write-code\n"
        )
        self.assertEqual(graph.workspace, "project")
        self.assertEqual(graph.workspace_for("spec-writer"), "specs")
        self.assertEqual(graph.workspace_for("spec-await-merge"), "specs")
        self.assertEqual(graph.workspace_for("write-code"), "project")

    def test_workspace_for_phase_resolves_a_phases_repo_across_its_stages(self):
        graph = parse_graph(
            "entry: spec-writer\n\n"
            "workspace:\n"
            "  spec-writer       specs\n"
            "  spec-await-merge  specs\n\n"
            "phase:\n"
            "  spec-writer       spec\n"
            "  spec-await-merge  spec\n"
            "  write-code        code\n\n"
            "edges:\n  spec-writer  done  write-code\n"
        )
        self.assertEqual(graph.workspace_for_phase("spec"), "specs")
        self.assertEqual(graph.workspace_for_phase("code"), "project")

    def test_workspace_for_phase_falls_back_to_the_default_for_an_undeclared_phase(self):
        graph = parse_graph("entry: build\n\nedges:\n  build  done  review\n")
        self.assertEqual(graph.workspace_for_phase(None), "project")
        self.assertEqual(graph.workspace_for_phase("code"), "project")

    def test_display_block_resolves_a_stage_to_its_declared_phrase(self):
        graph = parse_graph(
            "entry: code-await-merge\n\n"
            "display:\n"
            "  code-await-merge  Review the PR\n"
            "  write-code        Coding\n"
        )
        self.assertEqual(graph.display_for("code-await-merge"), "Review the PR")
        self.assertEqual(graph.display_for("write-code"), "Coding")

    def test_display_for_a_stage_absent_from_the_block_returns_none(self):
        graph = parse_graph(
            "entry: build\n\n"
            "display:\n"
            "  build  Coding\n"
        )
        self.assertIsNone(graph.display_for("review"))

    def test_display_for_returns_none_when_the_bundle_declares_no_display_block(self):
        graph = parse_graph("entry: build\n\nedges:\n  build  done  review\n")
        self.assertIsNone(graph.display_for("build"))

    def test_display_block_splits_only_on_the_first_run_of_whitespace(self):
        graph = parse_graph(
            "entry: code-await-merge\n\n"
            "display:\n"
            "  code-await-merge  Review the PR\n"
        )
        self.assertEqual(graph.display_for("code-await-merge"), "Review the PR")

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
