import unittest

from lightcycle.container import Container, worktrees_for


class _Collaborators:
    def __init__(self):
        self.store = object()
        self.git = object()
        self.fs = object()
        self.config = object()
        self.workflow_source = object()
        self.github = object()


class TestWorktreesFor(unittest.TestCase):
    def test_wires_every_collaborator(self):
        c = _Collaborators()

        svc = worktrees_for(c)

        self.assertIs(svc._store, c.store)
        self.assertIs(svc._git, c.git)
        self.assertIs(svc._fs, c.fs)
        self.assertIs(svc._config, c.config)
        self.assertIs(svc._github, c.github)

    def test_reuses_a_supplied_flow_instead_of_building_one(self):
        c = _Collaborators()
        flow = object()

        svc = worktrees_for(c, flow=flow)

        self.assertIs(svc._flow, flow)

    def test_container_worktrees_wires_the_github_port(self):
        github = object()
        container = Container(
            store=object(), git=object(), fs=object(), config=object(), github=github,
            workers=object(), spawner=object(),
        )

        self.assertIs(container.worktrees()._github, github)


if __name__ == "__main__":
    unittest.main()
