import unittest

from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.flow.remaining_stages import remaining_stages

GRAPH = """\
entry: write
edges:
  write done review
  review approved ship
  review rejected write
  ship done cleanup
  spin again spin
  watch ok
hooks:
  pr_feedback ship handle
  ci_failed_cap watch ci-failed 3 escalate
  review_rounds_cap watch rework escalate2
"""


def _remaining(entry, open_steps):
    graph = parse_graph(GRAPH)
    return remaining_stages(Flow.from_graph(graph, {}), entry or graph.entry, open_steps)


class TestRemainingStages(unittest.TestCase):
    def test_queued_stage_counts_itself_and_everything_after(self):
        self.assertEqual(
            _remaining(None, [("review", False)]),
            {"review", "ship", "write", "cleanup", "handle"})

    def test_running_stage_is_excluded_unless_a_rework_edge_returns_to_it(self):
        self.assertIn("review", _remaining(None, [("review", True)]))
        self.assertIn("write", _remaining(None, [("review", True)]))

    def test_running_stage_with_no_successors_is_empty(self):
        self.assertEqual(_remaining(None, [("cleanup", True)]), set())

    def test_queued_stage_with_no_successors_is_itself(self):
        self.assertEqual(_remaining(None, [("cleanup", False)]), {"cleanup"})

    def test_self_edge_terminates_and_brings_a_running_stage_back(self):
        self.assertEqual(_remaining(None, [("spin", True)]), {"spin"})

    def test_edge_without_target_adds_nothing(self):
        self.assertEqual(_remaining(None, [("watch", True)]), {"escalate", "escalate2"})

    def test_no_open_step_starts_from_entry_and_counts_it(self):
        self.assertEqual(
            _remaining(None, []), {"write", "review", "ship", "cleanup", "handle"})

    def test_hook_targets_are_followed(self):
        remaining = _remaining(None, [("ship", True)])
        self.assertIn("handle", remaining)
        self.assertEqual(_remaining(None, [("watch", False)]) - {"watch"}, {"escalate", "escalate2"})
