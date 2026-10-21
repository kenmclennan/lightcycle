from lightcycle.application.pool.accrual_gates import AccrualGatesUseCase
from lightcycle.application.pool.cadence_gates import CadenceGatesUseCase
from lightcycle.application.pool.no_op_gates import (
    NoOpBackupGate,
    NoOpBreakerGate,
    NoOpConfigReload,
    NoOpFlowService,
    NoOpFs,
    NoOpGhCallGate,
    NoOpGit,
    NoOpGithubBudget,
    NoOpGithubPollGate,
    NoOpGuidanceGate,
    NoOpHookCompletions,
    NoOpLifecycleGate,
    NoOpMemoryGate,
    NoOpMonitor,
    NoOpScheduleGate,
    NoOpScriptGate,
    NoOpSpinPort,
    NoOpStream,
    NoOpUsageGate,
    NoOpWorktrees,
)
from lightcycle.application.pool.sweep import SweepUseCase
from lightcycle.application.pool.tick import TickUseCase


def make_tick(store, workers, spawner, config, **overrides):
    def take(name, default):
        return overrides.pop(name, default)

    worker_log = take("worker_log", NoOpFs())
    sweep = take("sweep", None)
    worktrees = take("worktrees", NoOpWorktrees())
    git = take("git", NoOpGit())
    spin_port = take("spin_port", NoOpSpinPort())
    stream = take("stream", NoOpStream())
    if sweep is None:
        sweep = SweepUseCase(
            store, workers, worktrees, git, worker_log,
            spin_port=spin_port, spin_cap=config.spin_cap(), stream=stream,
        )
    cadence = take("cadence", None)
    schedule_gate = take("schedule_gate", NoOpScheduleGate())
    lifecycle_gate = take("lifecycle_gate", NoOpLifecycleGate())
    script_gate = take("script_gate", NoOpScriptGate())
    if cadence is None:
        cadence = CadenceGatesUseCase(schedule_gate, lifecycle_gate, script_gate)
    accrual = take("accrual", None)
    usage_gate = take("usage_gate", NoOpUsageGate())
    gh_call_gate = take("gh_call_gate", NoOpGhCallGate())
    if accrual is None:
        accrual = AccrualGatesUseCase(usage_gate, gh_call_gate)
    kwargs = dict(
        monitor=NoOpMonitor(), breaker_gate=NoOpBreakerGate(),
        hook_completions=NoOpHookCompletions(), backup_gate=NoOpBackupGate(),
        flow_service=NoOpFlowService(), memory_gate=NoOpMemoryGate(),
        github_poll_gate=NoOpGithubPollGate(), config_reload=NoOpConfigReload(),
        guidance_gate=NoOpGuidanceGate(), github_budget=NoOpGithubBudget(),
    )
    kwargs.update(overrides)
    return TickUseCase(
        store, workers, spawner, config, sweep=sweep, cadence=cadence, accrual=accrual,
        worker_log=worker_log, **kwargs,
    )
