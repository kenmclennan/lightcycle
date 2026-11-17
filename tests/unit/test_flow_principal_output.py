import unittest

from lightcycle.domain.flow.flow import Flow
from lightcycle.domain.flow.step_def import StepDef


def flow(**stages):
    return Flow({name: StepDef(**kw) for name, kw in stages.items()})


class TestFlowPrincipalOutput(unittest.TestCase):
    def test_one_declaring_stage_among_three_gives_the_phase_its_value(self):
        f = flow(
            write=dict(phase="spec", principal_output="spec"),
            open_pr=dict(phase="spec"),
            gate=dict(phase="spec"))
        for stage in ("write", "open_pr", "gate"):
            self.assertEqual(f.principal_output(stage), "spec")

    def test_two_stages_that_agree_give_the_value(self):
        f = flow(
            write=dict(phase="code", principal_output="code"),
            review=dict(phase="code", principal_output="code"))
        self.assertEqual(f.principal_output("review"), "code")

    def test_two_stages_that_disagree_give_none(self):
        f = flow(
            write=dict(phase="code", principal_output="spec"),
            review=dict(phase="code", principal_output="code"))
        self.assertIsNone(f.principal_output("write"))

    def test_a_phase_declaring_nothing_gives_none(self):
        f = flow(gate=dict(phase="code"))
        self.assertIsNone(f.principal_output("gate"))

    def test_a_stage_with_no_phase_gives_none(self):
        f = flow(write=dict(principal_output="code"))
        self.assertIsNone(f.principal_output("write"))

    def test_an_unknown_stage_gives_none(self):
        self.assertIsNone(flow(write=dict(phase="code", principal_output="code"))
                          .principal_output("ghost"))

    def test_phases_resolve_independently(self):
        f = flow(
            spec_write=dict(phase="spec", principal_output="spec"),
            spec_gate=dict(phase="spec"),
            code_write=dict(phase="code", principal_output="code"),
            code_gate=dict(phase="code"))
        self.assertEqual(f.principal_output("spec_gate"), "spec")
        self.assertEqual(f.principal_output("code_gate"), "code")
