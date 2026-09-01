import unittest

import lightcycle.cli as cli_mod


class FakeContainer:
    def __init__(self, github):
        self.store = object()
        self.git = object()
        self.fs = object()
        self.config = object()
        self.workflow_source = object()
        self.github = github


class TestCliWorktreesWiring(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def test_worktrees_wires_the_container_github_port(self):
        github = object()
        cli_mod.set_container(FakeContainer(github))

        worktrees = cli_mod._worktrees()

        self.assertIs(worktrees._github, github)


if __name__ == "__main__":
    unittest.main()
