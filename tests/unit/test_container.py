import unittest

from lightcycle.adapters.machine import MachineAdapter
from lightcycle.adapters.memory_gate_status import MemoryGateStatusAdapter
from lightcycle.container import Container, worktrees_for


class _Collaborators:
    def __init__(self):
        self.store = object()
        self.git = object()
        self.fs = object()
        self.config = object()
        self.workflow_source = object()
        self.workflow_bundle = object()
        self.scaffold = object()


class TestWorktreesFor(unittest.TestCase):
    def test_wires_every_collaborator(self):
        c = _Collaborators()

        svc = worktrees_for(c)

        self.assertIs(svc._store, c.store)
        self.assertIs(svc._git, c.git)
        self.assertIs(svc._fs, c.fs)
        self.assertIs(svc._config, c.config)
        self.assertIs(svc._scaffold, c.scaffold)

    def test_reuses_a_supplied_flow_instead_of_building_one(self):
        c = _Collaborators()
        flow = object()

        svc = worktrees_for(c, flow=flow)

        self.assertIs(svc._flow, flow)


class TestContainerMachineDefault(unittest.TestCase):
    def test_defaults_to_a_machine_adapter(self):
        c = Container(store=object())
        self.assertIsInstance(c.machine, MachineAdapter)

    def test_machine_override_is_honoured(self):
        sentinel = object()
        c = Container(store=object(), machine=sentinel)
        self.assertIs(c.machine, sentinel)


class TestContainerMemoryGateStatusDefault(unittest.TestCase):
    def test_defaults_to_a_memory_gate_status_adapter(self):
        c = Container(store=object())
        self.assertIsInstance(c.memory_gate_status, MemoryGateStatusAdapter)

    def test_memory_gate_status_override_is_honoured(self):
        sentinel = object()
        c = Container(store=object(), memory_gate_status=sentinel)
        self.assertIs(c.memory_gate_status, sentinel)


if __name__ == "__main__":
    unittest.main()
