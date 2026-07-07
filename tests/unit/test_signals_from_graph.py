import unittest
from dataclasses import dataclass

from lightcycle.domain.feedback.signal import Signals
from lightcycle.domain.flow.graph import parse_graph


@dataclass
class FakeNode:
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
        steps = [
            FakeNode("review", "rejected"),
            FakeNode("review", "done"),
            FakeNode("build", "rejected"),
        ]
        self.assertEqual(self.signals.tally(steps)["review_rounds"], {"sonnet": 1})

    def test_contains_match_for_tilde_declaration(self):
        steps = [FakeNode("open-pr", "had-a-conflict-mid-run")]
        self.assertEqual(self.signals.tally(steps)["conflicts"], {"sonnet": 1})
