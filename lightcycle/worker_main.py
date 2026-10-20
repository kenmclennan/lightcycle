import os
import sys

from lightcycle.adapters.sqlite_store import LiveStoreRefused, SchemaVersionRefused
from lightcycle.adapters.worker_session import (
    SessionError, plan_session, record_guidance, run, session_cwd,
)
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.claim_step import ClaimInput, ClaimStepUseCase
from lightcycle.application.flow.select_guidance import SelectGuidanceUseCase
from lightcycle.container import Container


def main():
    try:
        container = Container()
    except (LiveStoreRefused, SchemaVersionRefused) as e:
        sys.stderr.write("worker_main: %s\n" % e)
        return 1
    config = container.config
    role = config.worker_role()
    spawnid = config.spawn_id()
    if not (role and spawnid):
        sys.stderr.write("worker_main: LC_ROLE, LC_SPAWNID required\n")
        return 1
    claim = ClaimStepUseCase(
        container.store, container.flow_service(), container.worktrees(),
        container.workers, config, container.github_budget(),
    )
    select = SelectGuidanceUseCase(container.store, container.fs, container.git, config)
    try:
        plan = plan_session(
            lambda r: claim.execute(ClaimInput(role=r)),
            lambda r, pin: container.workflow_source.resolve_agent(r, pin),
            container.store.reclaim,
            role,
            guidance=lambda resp: select.execute(
                resp.view.step.item, resp.view.step.stage, resp.pin, resp.view.step.id),
        )
    except (SessionError, UseCaseError) as e:
        sys.stderr.write("worker_main: %s\n" % e)
        return 1
    if plan is None:
        return 0
    record_guidance(container.store, plan)
    with session_cwd(plan.workspace) as cwd:
        return run(
            config.data_root(), cwd, plan.stage, spawnid, plan.model, plan.sysprompt,
            config.max_session_seconds(),
            env=config.agent_env(),
            record_session_id=lambda sid: container.store.replace_artifact(
                plan.step_id, "session-id", sid, internal=True
            ),
        )


if __name__ == "__main__":
    _rc = main()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except (ValueError, OSError):
        pass
    os._exit(_rc if isinstance(_rc, int) else 0)
