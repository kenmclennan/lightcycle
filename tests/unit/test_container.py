import unittest

from lightcycle.container import worktrees_for


class _Collaborators:
    def __init__(self):
        self.store = object()
        self.git = object()
        self.fs = object()
        self.config = object()
        self.workflow_source = object()


class TestWorktreesFor(unittest.TestCase):
    def test_wires_every_collaborator(self):
        c = _Collaborators()

        svc = worktrees_for(c)

        self.assertIs(svc._store, c.store)
        self.assertIs(svc._git, c.git)
        self.assertIs(svc._fs, c.fs)
        self.assertIs(svc._config, c.config)

    def test_reuses_a_supplied_flow_instead_of_building_one(self):
        c = _Collaborators()
        flow = object()

        svc = worktrees_for(c, flow=flow)

        self.assertIs(svc._flow, flow)


if __name__ == "__main__":
    unittest.main()
