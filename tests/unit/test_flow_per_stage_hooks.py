import unittest

from lightcycle.domain.flow.flow import Flow
from lightcycle.domain.flow.graph import parse_graph

_TWO_MERGE = """
entry: spec-writer

nodes:
  spec-await-merge  await-merge
  code-await-merge  await-merge

edges:
  spec-await-merge  spec-merged  write-code
  code-await-merge  merged       cleanup

hooks:
  pr_merge  spec-await-merge  spec-merged
  pr_merge  code-await-merge  merged
  pr_close  spec-await-merge  abandoned
  pr_close  code-await-merge  abandoned
"""


class TestPerStageHooks(unittest.TestCase):
    def test_each_await_merge_stage_has_its_own_merge_outcome(self):
        flow = Flow.from_graph(parse_graph(_TWO_MERGE), {})
        self.assertEqual(flow.step_def("spec-await-merge").pr_merge, "spec-merged")
        self.assertEqual(flow.step_def("code-await-merge").pr_merge, "merged")

    def test_close_outcome_is_per_stage(self):
        flow = Flow.from_graph(parse_graph(_TWO_MERGE), {})
        self.assertEqual(flow.step_def("spec-await-merge").pr_close, "abandoned")
        self.assertEqual(flow.step_def("code-await-merge").pr_close, "abandoned")

    def test_unknown_stage_has_no_merge_outcome(self):
        flow = Flow.from_graph(parse_graph(_TWO_MERGE), {})
        self.assertIsNone(flow.step_def("write-code").pr_merge)

    def test_single_hook_still_works(self):
        graph = parse_graph(
            "entry: build\n\nedges:\n  await-merge  merged  cleanup\n\n"
            "hooks:\n  pr_merge  await-merge  merged\n"
        )
        flow = Flow.from_graph(graph, {})
        self.assertEqual(flow.step_def("await-merge").pr_merge, "merged")


if __name__ == "__main__":
    unittest.main()
