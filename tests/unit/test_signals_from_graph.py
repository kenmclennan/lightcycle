import unittest
from dataclasses import dataclass

from the_grid.domain.feedback.signal import Signals
from the_grid.domain.flow.graph import parse_graph


@dataclass
class FakeTask:
    step: str
    outcome: str
    model: str = "sonnet"


class TestSignalsFromGraph(unittest.TestCase):
    def setUp(self):
        graph = parse_graph(
            "entry: build\n"
            "\n"
            "signals:\n"
            "  review   review_rounds  rejected\n"
            "  open-pr  conflicts      ~conflict\n"
        )
        self.signals = Signals.from_graph(graph)

    def test_exact_outcome_tally_by_step(self):
        tasks = [
            FakeTask("review", "rejected"),
            FakeTask("review", "done"),
            FakeTask("build", "rejected"),
        ]
        self.assertEqual(self.signals.tally(tasks)["review_rounds"], {"sonnet": 1})

    def test_contains_match_for_tilde_declaration(self):
        tasks = [FakeTask("open-pr", "had-a-conflict-mid-run")]
        self.assertEqual(self.signals.tally(tasks)["conflicts"], {"sonnet": 1})
