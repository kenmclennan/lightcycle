import unittest

from lightcycle.domain.contracts import FlowContracts
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT, contract_compatible


class TestEngineContract(unittest.TestCase):
    def test_engine_contract_is_one(self):
        self.assertEqual(ENGINE_CONTRACT, 1)

    def test_same_contract_is_compatible(self):
        self.assertTrue(contract_compatible(ENGINE_CONTRACT))

    def test_higher_source_contract_is_incompatible(self):
        self.assertFalse(contract_compatible(ENGINE_CONTRACT + 1))

    def test_lower_source_contract_is_incompatible(self):
        self.assertFalse(contract_compatible(ENGINE_CONTRACT - 1))


_ROUTE_METAS = {
    "gate": {},
    "other-gate": {},
    "fb": {"model": "x"},
    "rework-stage": {"model": "x"},
    "orphan": {"model": "x"},
}

_VALID_ROUTE_GRAPH = """
entry: gate

edges:
  gate          changes  rework-stage
  gate          merged   done-end
  fb            done
  fb            rework
  rework-stage  done

hooks:
  pr_feedback        gate  fb
  pr_feedback_route  fb  rework  changes
"""


def _route_contracts(text):
    graph = parse_graph(text)
    return FlowContracts(Flow.from_graph(graph, _ROUTE_METAS), graph, _ROUTE_METAS)


class TestFeedbackRouteDeclaration(unittest.TestCase):
    def test_a_valid_declaration_reports_no_problem(self):
        self.assertEqual(_route_contracts(_VALID_ROUTE_GRAPH).feedback_route_problems(), [])

    def test_feedback_route_names_outcome_the_watched_stage_rejects(self):
        text = _VALID_ROUTE_GRAPH.replace("rework  changes", "rework  sideways")
        problems = _route_contracts(text).feedback_route_problems()
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0][:2], ("fb", "rework"))
        self.assertIn("gate", problems[0][2])
        self.assertIn("sideways", problems[0][2])
        self.assertFalse(_route_contracts(text).ok())

    def test_a_watched_outcome_that_routes_to_no_target_is_reported(self):
        text = _VALID_ROUTE_GRAPH.replace("gate          changes  rework-stage", "gate          changes")
        problems = _route_contracts(text).feedback_route_problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("no next step", problems[0][2])

    def test_a_watched_outcome_that_ends_the_pass_is_reported(self):
        text = _VALID_ROUTE_GRAPH + "\npass-end:\n  gate  changes\n"
        problems = _route_contracts(text).feedback_route_problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("ends the pass", problems[0][2])

    def test_a_feedback_outcome_the_stage_lacks_is_reported(self):
        text = _VALID_ROUTE_GRAPH.replace("  fb            rework\n", "")
        problems = _route_contracts(text).feedback_route_problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("not an outcome of fb", problems[0][2])

    def test_a_stage_that_watches_no_gate_is_reported(self):
        text = _VALID_ROUTE_GRAPH.replace("  pr_feedback        gate  fb\n", "")
        problems = _route_contracts(text).feedback_route_problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("watches no gate", problems[0][2])

    def test_a_stage_watched_by_two_gates_reports_only_the_failing_gate(self):
        text = _VALID_ROUTE_GRAPH.replace(
            "hooks:\n", "hooks:\n  pr_feedback        other-gate  fb\n"
        ).replace(
            "  fb            done\n", "  other-gate    merged  done-end\n  fb            done\n"
        )
        problems = _route_contracts(text).feedback_route_problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("other-gate", problems[0][2])
        self.assertNotIn("gate does not", problems[0][2].replace("other-gate", ""))


if __name__ == "__main__":
    unittest.main()
