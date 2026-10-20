import unittest

from lightcycle.adapters.guidance_sync_status import GuidanceSyncStatusAdapter
from lightcycle.adapters.machine import MachineAdapter
from lightcycle.adapters.config_reload_status import ConfigReloadStatusAdapter
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


class TestContainerGuidanceSyncStatusDefault(unittest.TestCase):
    def test_defaults_to_a_guidance_sync_status_adapter(self):
        c = Container(store=object())
        self.assertIsInstance(c.guidance_sync_status, GuidanceSyncStatusAdapter)

    def test_guidance_sync_status_override_is_honoured(self):
        sentinel = object()
        c = Container(store=object(), guidance_sync_status=sentinel)
        self.assertIs(c.guidance_sync_status, sentinel)


if __name__ == "__main__":
    unittest.main()


class TestContainerConfigReloadStatusDefault(unittest.TestCase):
    def test_defaults_to_a_config_reload_status_adapter(self):
        c = Container(store=object())
        self.assertIsInstance(c.config_reload_status, ConfigReloadStatusAdapter)

    def test_config_reload_status_override_is_honoured(self):
        sentinel = object()
        c = Container(store=object(), config_reload_status=sentinel)
        self.assertIs(c.config_reload_status, sentinel)


class TestContainerTickGithubPoll(unittest.TestCase):
    def _config(self, **filevals):
        import os
        import tempfile
        from pathlib import Path

        from lightcycle.config import Config

        path = os.path.join(tempfile.mkdtemp(), "config")
        Path(path).write_text(
            "".join("%s: %s\n" % (k.replace("_", "-"), v) for k, v in filevals.items()))
        return Config(environ={"LC_CONFIG": path})

    def test_tick_without_github_poll_seconds_fails_naming_the_key(self):
        from lightcycle.config import ConfigError

        container = Container(store=object(), config=self._config(spin_cap="3"))

        with self.assertRaises(ConfigError) as ctx:
            container.tick(flow=object())

        self.assertIn("github-poll-seconds", str(ctx.exception))

    def test_tick_wires_the_monitor_over_a_snapshot_not_the_real_port(self):
        from lightcycle.application.pool.pr_snapshot import PrSnapshot

        container = Container(
            store=object(), github=object(),
            config=self._config(spin_cap="3", github_poll_seconds="60"))

        tick = container.tick(flow=object())

        self.assertIsInstance(tick._monitor._github, PrSnapshot)
