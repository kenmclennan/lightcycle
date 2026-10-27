import sys

from lightcycle.application.pool import PoolDrainStatusUseCase
from lightcycle.commands.context import container
from lightcycle.domain.work import render_cap_refusal


def refuse_over_cap(fields):
    refusal = render_cap_refusal(fields)
    if not refusal:
        return None
    sys.stderr.write("%s\n" % refusal)
    return 2


def named(node_type):
    return "an item" if node_type == "item" else "a step"


def render_field_refusal(refusal):
    fields = ", ".join("--%s" % f for f in refusal.fields)
    verb = "belong" if len(refusal.fields) > 1 else "belongs"
    if refusal.owner is None:
        return "%s %s to no structure" % (fields, verb)
    return "%s %s to %s, not %s" % (
        fields, verb, named(refusal.owner), named(refusal.requested_type),
    )


def drain_status(now, pool_running=True):
    return PoolDrainStatusUseCase(
        container().drain, container().workers, container().store
    ).execute(pool_running, now)
