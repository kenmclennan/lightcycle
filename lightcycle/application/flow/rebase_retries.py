from lightcycle.domain.work.node_id import node_id_key
from lightcycle.domain.work.state import State
from lightcycle.domain.work.timestamp import parse_timestamp

_LINE_PREFIX = "rebase-retried:"


def checks_of(note):
    lines = (note or "").splitlines()
    marked = [
        line.strip()[len(_LINE_PREFIX):].split(";", 1)[0].strip()
        for line in lines if line.strip().casefold().startswith(_LINE_PREFIX)
    ]
    if marked:
        return [c for c in marked if c]
    return []


def earlier_rebase_retries(store, flows, step):
    name = flows.workflow_for(step)
    retry = flows.load_flow(name).rebase_retry(step.stage)
    phase = flows.phase_for_stage(step.stage, name)
    if retry is None or phase is None:
        return {}
    run = store.current_run(step.item, phase)
    if run is None:
        return {}
    floor = parse_timestamp(run.opened_at)
    earlier = sorted(
        (
            s for s in store.steps_at_step(step.stage)
            if s.item == step.item and s.id != step.id
            and s.state == State.DONE and s.outcome in retry.retry_outcomes
            and (floor is None or parse_timestamp(s.created_at) >= floor)
        ),
        key=lambda s: (parse_timestamp(s.created_at), node_id_key(s.id)),
    )
    seen = {}
    for s in earlier:
        for check in checks_of(s.report):
            if check.casefold() not in {c.casefold() for c in seen}:
                seen[check] = s.id
    return seen


def repeated_checks(earlier, note):
    folded = {c.casefold(): (c, sid) for c, sid in earlier.items()}
    out = {}
    for check in checks_of(note):
        hit = folded.get(check.casefold())
        if hit is not None:
            out[hit[0]] = hit[1]
    return out
