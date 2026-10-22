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

        container = Container(
            store=object(),
            config=self._config(spin_cap="3", ci_check_ceiling_seconds="3600", ci_start_window_seconds="600", ci_no_workflows_wait_seconds="60", ci_unconfirmed_note_polls="3"))

        with self.assertRaises(ConfigError) as ctx:
            container.tick(flow=object())

        self.assertIn("github-poll-seconds", str(ctx.exception))

    def test_tick_without_github_view_refresh_polls_fails_naming_the_key(self):
        from lightcycle.config import ConfigError

        container = Container(
            store=object(), config=self._config(
                spin_cap="3", github_poll_seconds="60", github_reserve_calls="750",
                ci_check_ceiling_seconds="3600", ci_start_window_seconds="600", ci_no_workflows_wait_seconds="60", ci_unconfirmed_note_polls="3"))

        with self.assertRaises(ConfigError) as ctx:
            container.tick(flow=object())

        self.assertIn("github-view-refresh-polls", str(ctx.exception))

    def test_tick_wires_the_monitor_over_a_snapshot_not_the_real_port(self):
        from lightcycle.application.pool.pr_snapshot import PrSnapshot

        container = Container(
            store=object(), github=object(),
            config=self._config(
                spin_cap="3", github_poll_seconds="60", github_reserve_calls="750",
                ci_check_ceiling_seconds="3600", ci_start_window_seconds="600", ci_no_workflows_wait_seconds="60", ci_unconfirmed_note_polls="3", github_view_refresh_polls="10"))

        tick = container.tick(flow=object())

        self.assertIsInstance(tick._monitor._github, PrSnapshot)

    def test_tick_without_ci_check_ceiling_fails_naming_the_key(self):
        from lightcycle.config import ConfigError

        container = Container(
            store=object(),
            config=self._config(
                spin_cap="3", github_poll_seconds="60", github_reserve_calls="750"))

        with self.assertRaises(ConfigError) as ctx:
            container.tick(flow=object())

        self.assertIn("ci-check-ceiling-seconds", str(ctx.exception))

    def test_tick_without_github_reserve_calls_fails_naming_the_key(self):
        from lightcycle.config import ConfigError

        container = Container(
            store=object(), config=self._config(
                spin_cap="3", github_poll_seconds="60", ci_check_ceiling_seconds="3600", ci_start_window_seconds="600", ci_no_workflows_wait_seconds="60", ci_unconfirmed_note_polls="3",
                github_view_refresh_polls="10"))

        with self.assertRaises(ConfigError) as ctx:
            container.tick(flow=object())

        self.assertIn("github-reserve-calls", str(ctx.exception))


class TestContainerSimulation(unittest.TestCase):
    def _container(self):
        from unittest import mock

        container = Container(store=object())
        container.workflow_lifecycle = mock.Mock()
        return container

    def test_the_scratch_dir_exists_inside_and_is_gone_after(self):
        import os
        from unittest import mock

        seen = []

        def fake_sim(container, scratch):
            seen.append(scratch)
            return mock.Mock()

        with mock.patch("lightcycle.container.SimulationContainer", fake_sim), \
                mock.patch("lightcycle.application.workflows.simulate.WorkflowSimulateUseCase"):
            with self._container().simulation():
                self.assertTrue(os.path.isdir(seen[0]))
        self.assertFalse(os.path.exists(seen[0]))

    def test_the_scratch_dir_is_removed_when_the_body_raises(self):
        import os
        from unittest import mock

        seen = []

        def fake_sim(container, scratch):
            seen.append(scratch)
            return mock.Mock()

        with mock.patch("lightcycle.container.SimulationContainer", fake_sim), \
                mock.patch("lightcycle.application.workflows.simulate.WorkflowSimulateUseCase"):
            with self.assertRaises(RuntimeError):
                with self._container().simulation():
                    raise RuntimeError("boom")
        self.assertFalse(os.path.exists(seen[0]))

    def test_the_scratch_dir_is_removed_when_wiring_raises(self):
        import os
        from unittest import mock

        seen = []

        def fake_sim(container, scratch):
            seen.append(scratch)
            raise RuntimeError("boom")

        with mock.patch("lightcycle.container.SimulationContainer", fake_sim):
            with self.assertRaises(RuntimeError):
                with self._container().simulation():
                    pass
        self.assertFalse(os.path.exists(seen[0]))


class TestContainerStopPool(unittest.TestCase):
    def test_returns_a_stop_pool_over_the_containers_workers_and_sweep(self):
        from unittest import mock

        from lightcycle.application.pool.stop_pool import StopPoolUseCase

        workers = object()
        container = Container(store=object(), workers=workers)
        sweep = object()
        container.sweep = mock.Mock(return_value=sweep)

        use_case = container.stop_pool(flow="f")

        self.assertIsInstance(use_case, StopPoolUseCase)
        self.assertIs(use_case._workers, workers)
        self.assertIs(use_case._sweep, sweep)
        container.sweep.assert_called_once_with(flow="f")


class TestContainerClockSeam(unittest.TestCase):
    def test_stop_pool_receives_the_injected_sleep_and_monotonic_clock(self):
        from unittest import mock

        def sleep(seconds):
            return None

        def monotonic():
            return 1.0

        container = Container(
            store=object(), workers=object(), sleep=sleep, monotonic=monotonic)
        container.sweep = mock.Mock(return_value=object())

        use_case = container.stop_pool()

        self.assertIs(use_case._sleep, sleep)
        self.assertIs(use_case._clock, monotonic)

    def test_defaults_are_the_real_time_functions(self):
        import time

        container = Container(store=object(), workers=object())

        self.assertIs(container.clock, time.time)
        self.assertIs(container.monotonic, time.monotonic)
        self.assertIs(container.sleep, time.sleep)
