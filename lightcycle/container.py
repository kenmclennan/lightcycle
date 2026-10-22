import os
import shutil
import tempfile
import time

from lightcycle.adapters.backup import SqliteBackupAdapter
from lightcycle.adapters.breaker import BreakerAdapter
from lightcycle.adapters.claude_stream import ClaudeStreamAdapter
from lightcycle.adapters.drain import PoolDrainAdapter
from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.gh_shim import GhShimAdapter
from lightcycle.adapters.github import GitHubEventsAdapter
from lightcycle.adapters.github_budget_status import GithubBudgetStatusAdapter
from lightcycle.adapters.gitio import GitAdapter
from lightcycle.adapters.launcher import LauncherAdapter
from lightcycle.adapters.lifecycle_runner import LifecycleRunnerAdapter
from lightcycle.application.pool.accrual_gates import AccrualGatesUseCase
from lightcycle.application.pool.cadence_gates import CadenceGatesUseCase
from lightcycle.application.pool.stop_pool import StopPoolUseCase
from lightcycle.application.workflows.script_tooling import WorkflowScripts
from lightcycle.application.workflows.simulate import WorkflowSimulateUseCase
from lightcycle.application.pool.gh_call_accrual import GhCallAccrualUseCase
from lightcycle.application.pool.github_budget import GithubBudgetUseCase
from lightcycle.application.pool.github_poll import GithubPollUseCase
from lightcycle.application.pool.pr_snapshot import PrSnapshot
from lightcycle.application.pool.pr_writes import PrWrites
from lightcycle.adapters.github_poll_runner import GithubPollRunnerAdapter
from lightcycle.adapters.script_runner import ScriptRunnerAdapter
from lightcycle.adapters.lock import RunLockAdapter
from lightcycle.adapters.run_groups import RunGroupsAdapter
from lightcycle.adapters.machine import MachineAdapter
from lightcycle.adapters.guidance_sync_status import GuidanceSyncStatusAdapter
from lightcycle.adapters.config_reload_status import ConfigReloadStatusAdapter
from lightcycle.application.pool.reload_config import ReloadConfigUseCase
from lightcycle.adapters.memory_gate_status import MemoryGateStatusAdapter
from lightcycle.adapters.scaffold import ScaffoldAdapter
from lightcycle.adapters.spawner import SpawnerAdapter
from lightcycle.adapters.spin import SpinAdapter
from lightcycle.adapters.simulate import ScriptedGitHub
from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.adapters.upgrade import UpgradeAdapter
from lightcycle.adapters.worker_log import WorkerLogAdapter
from lightcycle.adapters.workers import WorkersAdapter
from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter
from lightcycle.adapters.workflow_source import WorkflowSourceAdapter
from lightcycle.application.pool.guidance_sync import GuidanceSyncUseCase
from lightcycle.application.pool.lifecycle_cadence import LifecycleCadenceUseCase
from lightcycle.application.flow.park_step import ParkStepUseCase
from lightcycle.application.pool.schedule_cadence import ScheduleCadenceUseCase
from lightcycle.application.pool.script_stages import ScriptStageUseCase
from lightcycle.application.work.activate_item import ActivateItemUseCase
from lightcycle.application.workflows.lifecycle import WorkflowLifecycleService
from lightcycle.config import Config


class Container:
    def __init__(
        self, *, config=None, store=None, git=None, spawner=None, workers=None, fs=None,
        github=None, lock=None, breaker=None, backup=None, workflow_source=None, launcher=None,
        spin=None, now=None, workflow_bundle=None, worker_log=None, scaffold=None, upgrade=None,
        claude_stream=None, machine=None, memory_gate_status=None,
        drain=None, guidance_sync_status=None, config_reload_status=None,
        lifecycle_runner=None, script_runner=None, github_poll_runner=None,
        github_budget_status=None, gh_shim=None, run_groups=None,
        clock=time.time, monotonic=time.monotonic, sleep=time.sleep,
    ):
        self.clock = clock
        self.monotonic = monotonic
        self.sleep = sleep
        self.config = config if config is not None else Config()
        self.store = store if store is not None else SqliteStore(self.config, now=now)
        self.git = git if git is not None else GitAdapter()
        self.spawner = spawner if spawner is not None else SpawnerAdapter(self.config)
        self.workers = workers if workers is not None else WorkersAdapter(self.config)
        self.fs = fs if fs is not None else FsAdapter(self.config)
        self.workflow_bundle = (
            workflow_bundle if workflow_bundle is not None else WorkflowBundleAdapter()
        )
        self.worker_log = worker_log if worker_log is not None else WorkerLogAdapter(self.config)
        self.scaffold = scaffold if scaffold is not None else ScaffoldAdapter()
        self.github = github if github is not None else GitHubEventsAdapter()
        self.lock = lock if lock is not None else RunLockAdapter(self.config)
        self.drain = drain if drain is not None else PoolDrainAdapter(self.config)
        self.breaker = breaker if breaker is not None else BreakerAdapter(self.config)
        self.spin = spin if spin is not None else SpinAdapter(self.config)
        self.backup = backup if backup is not None else SqliteBackupAdapter(self.config)
        self.workflow_source = (
            workflow_source if workflow_source is not None
            else WorkflowSourceAdapter(self.config, self.workflow_bundle)
        )
        self.run_groups = run_groups if run_groups is not None else RunGroupsAdapter()
        self.lifecycle_runner = (
            lifecycle_runner if lifecycle_runner is not None
            else LifecycleRunnerAdapter(self.config, self.run_groups)
        )
        self.script_runner = (
            script_runner if script_runner is not None
            else ScriptRunnerAdapter(self.config, self.run_groups)
        )
        self.github_poll_runner = (
            github_poll_runner if github_poll_runner is not None
            else GithubPollRunnerAdapter(self.worker_log)
        )
        self.launcher = launcher if launcher is not None else LauncherAdapter()
        self.upgrade = upgrade if upgrade is not None else UpgradeAdapter(self.config)
        self.claude_stream = claude_stream if claude_stream is not None else ClaudeStreamAdapter()
        self.machine = machine if machine is not None else MachineAdapter()
        self.memory_gate_status = (
            memory_gate_status if memory_gate_status is not None
            else MemoryGateStatusAdapter(self.config)
        )
        self.github_budget_status = (
            github_budget_status if github_budget_status is not None
            else GithubBudgetStatusAdapter(self.config)
        )
        self.gh_shim = gh_shim if gh_shim is not None else GhShimAdapter(self.config)
        self.config_reload_status = (
            config_reload_status if config_reload_status is not None
            else ConfigReloadStatusAdapter(self.config)
        )
        self.guidance_sync_status = (
            guidance_sync_status if guidance_sync_status is not None
            else GuidanceSyncStatusAdapter(self.config)
        )

    def workflow_lifecycle(self):
        return WorkflowLifecycleService(
            self.workflow_source, self.workflow_bundle, self.config, self.lifecycle_runner)

    def flow_service(self):
        return make_flow_service(self.workflow_bundle, self.store, self.config, self.workflow_source)

    def worktrees(self, flow=None):
        return worktrees_for(self, flow=flow)

    def github_budget(self, flow=None):
        return GithubBudgetUseCase(
            self.github_budget_status, flow if flow is not None else self.flow_service(),
            self.config, self.clock)

    def tick(self, flow=None):
        from lightcycle.application.flow.complete_step import CompleteStepUseCase
        from lightcycle.application.pool.backup import BackupUseCase
        from lightcycle.application.pool.breaker_gate import BreakerGateUseCase
        from lightcycle.application.pool.hook_completions import HookCompletionsUseCase
        from lightcycle.application.pool.memory_gate import MemoryGateUseCase
        from lightcycle.application.pool.monitor_prs import MonitorPrsUseCase
        from lightcycle.application.pool.close_stranded_items import CloseStrandedItemsUseCase
        from lightcycle.application.pool.release_interrupted_runs import (
            ReleaseInterruptedRunsUseCase,
        )
        from lightcycle.application.pool.tick import TickUseCase
        from lightcycle.application.pool.live_usage import LiveUsageAccrualUseCase

        flow = flow if flow is not None else self.flow_service()
        worktrees = worktrees_for(self, flow=flow)
        complete = CompleteStepUseCase(self.store, flow, worktrees, self.config)
        snapshot = PrSnapshot(self.github)
        writes = PrWrites(self.monotonic)
        return TickUseCase(
            self.store,
            self.workers,
            self.spawner,
            self.config,
            monitor=MonitorPrsUseCase(
                self.store, snapshot, worktrees, flow, complete,
                trusted_authors=self.config.trusted_authors,
                held_shortcode=self.config.held_comment_shortcode, writes=writes,
                ci_clock=self.monotonic, ci_poll_seconds=self.config.github_poll_seconds,
                ci_ceiling_seconds=self.config.ci_check_ceiling_seconds,
                ci_start_window_seconds=self.config.ci_start_window_seconds,
                ci_no_workflows_wait_seconds=self.config.ci_no_workflows_wait_seconds,
                ci_unconfirmed_note_polls=self.config.ci_unconfirmed_note_polls,
                ci_wall_clock=self.clock,
                ci_views=snapshot,
            ),
            breaker_gate=BreakerGateUseCase(
                self.workers, self.worker_log, self.breaker, self.config, self.claude_stream,
                spin_port=self.spin, store=self.store,
            ),
            github_poll_gate=GithubPollUseCase(
                snapshot, self.github, self.github_poll_runner, self.config, writes,
                self.github_budget_status, self.clock, self.worker_log, self.store),
            hook_completions=HookCompletionsUseCase(self.store, flow),
            backup_gate=BackupUseCase(self.backup, self.config),
            flow_service=flow,
            memory_gate=MemoryGateUseCase(self.machine, self.config, self.memory_gate_status),
            guidance_gate=GuidanceSyncUseCase(
                self.store, self.git, self.fs, self.guidance_sync_status, self.config,
            ),
            github_budget=self.github_budget(flow),
            release_gate=ReleaseInterruptedRunsUseCase(self.store, worktrees),
            stranded_gate=CloseStrandedItemsUseCase(self.store, worktrees),
            config_reload=ReloadConfigUseCase(
                self.config, self.config_reload_status, os.getpid()),
            sweep=self.sweep(flow=flow, worktrees=worktrees),
            cadence=CadenceGatesUseCase(
                ScheduleCadenceUseCase(
                    self.store, self.config, flow, self.workflow_source, self.git,
                    ActivateItemUseCase(
                        self.store, flow, self.git, self.config, self.scaffold),
                    self.script_runner, self.workflow_lifecycle(),
                ),
                LifecycleCadenceUseCase(
                    self.store, self.config, self.workflow_source, self.workflow_lifecycle(),
                    self.lifecycle_runner, self.config.audit_shortcode,
                ),
                ScriptStageUseCase(
                    self.store, flow, self.config, self.workflow_source,
                    self.workflow_lifecycle(), self.script_runner, ParkStepUseCase(self.store),
                    complete, worktrees,
                ),
            ),
            accrual=AccrualGatesUseCase(
                LiveUsageAccrualUseCase(
                    self.store, self.worker_log, self.workers, self.config, self.claude_stream,
                ),
                GhCallAccrualUseCase(self.store, self.worker_log, self.workers, self.config),
            ),
            worker_log=self.worker_log,
        )

    def sweep(self, flow=None, worktrees=None):
        from lightcycle.application.pool.sweep import SweepUseCase

        flow = flow if flow is not None else self.flow_service()
        return SweepUseCase(
            self.store, self.workers,
            worktrees=worktrees if worktrees is not None else worktrees_for(self, flow=flow),
            git=self.git, worker_log=self.worker_log,
            spin_port=self.spin, spin_cap=self.config.spin_cap(),
            stream=self.claude_stream,
        )

    def stop_pool(self, flow=None):
        return StopPoolUseCase(
            self.workers, self.sweep(flow=flow), self.run_groups, sleep=self.sleep,
            clock=self.monotonic)

    def simulation(self):
        return _Simulation(self)

    def unblock_step_use_case(self, flow=None):
        from lightcycle.application.flow.unblock_step import UnblockStepUseCase

        return UnblockStepUseCase(
            self.store, flow if flow is not None else self.flow_service(), spin_port=self.spin
        )


def make_flow_service(workflow_bundle, store, config, workflow_source):
    from lightcycle.application.services.flow import FlowService

    return FlowService(workflow_bundle, store, config, workflow_source)


def make_worktrees(store, git, fs, config, flow, scaffold=None):
    from lightcycle.application.services.worktree import WorktreeService

    return WorktreeService(store, git, fs, config, flow, scaffold=scaffold)


def worktrees_for(container, flow=None):
    if flow is None:
        flow = make_flow_service(
            container.workflow_bundle, container.store, container.config, container.workflow_source
        )
    return make_worktrees(
        container.store, container.git, container.fs, container.config, flow, container.scaffold,
    )


class _Simulation:
    def __init__(self, container):
        self._container = container
        self._scratch = None

    def __enter__(self):
        container = self._container
        self._scratch = tempfile.mkdtemp(prefix="lc-simulate-")
        try:
            sim = SimulationContainer(container, self._scratch)
            return WorkflowSimulateUseCase(
                sim.store, sim.flow, sim.worktrees, sim.claim, sim.complete, sim.projects_root,
                sim.git, lifecycle=container.workflow_lifecycle(),
                scripts=WorkflowScripts(
                    container.workflow_bundle, container.fs, container.config),
                source=container.workflow_source, scaffold=sim.scaffold,
                github_factory=ScriptedGitHub, config=sim.config,
            )
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type, exc, tb):
        shutil.rmtree(self._scratch, ignore_errors=True)
        return False


class SimulationContainer:
    def __init__(self, container, scratch):
        from lightcycle.adapters.sqlite_store import SqliteStore
        from lightcycle.application.flow.claim_step import ClaimStepUseCase
        from lightcycle.application.flow.complete_step import CompleteStepUseCase
        from lightcycle.adapters.simulate import (
            NullGithubBudget, NullWorkers, RecordingGit, SimulateConfig,
        )
        from lightcycle.config import Config

        self.home = os.path.join(scratch, "home")
        self.specs_root = os.path.join(scratch, "specs")
        self.projects_root = os.path.join(scratch, "projects")
        for d in (self.home, self.specs_root, self.projects_root):
            os.makedirs(d, exist_ok=True)
        cfg_path = os.path.join(self.home, "config")

        with open(cfg_path, "w") as f:
            f.write("context-artifact-types: %s\n" % " ".join(sorted(container.config.context_artifact_types())))
            f.write("context-artifact-project: %s\n" % container.config.context_artifact_project())
        self.config = SimulateConfig(container.config, self.projects_root)
        self.store = SqliteStore(Config(environ={"LC_HOME": self.home, "LC_CONFIG": cfg_path}))
        self.store.add_project(self.config.context_artifact_project(), local_path=self.specs_root)
        self.git = RecordingGit()
        self.scaffold = container.scaffold
        self.flow = make_flow_service(
            container.workflow_bundle, self.store, container.config, container.workflow_source
        )
        self.worktrees = make_worktrees(
            self.store, self.git, container.fs, self.config, self.flow, container.scaffold
        )
        self.claim = ClaimStepUseCase(
            self.store, self.flow, self.worktrees, NullWorkers(), self.config, NullGithubBudget()
        )
        self.complete = CompleteStepUseCase(self.store, self.flow, self.worktrees, self.config)
