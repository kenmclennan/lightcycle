from lightcycle.application.errors import UseCaseError
from lightcycle.domain.work import State


def link_resolves(store, work_id, backlog_ids):
    for backlog_id in backlog_ids:
        try:
            store.get_node(backlog_id)
        except KeyError:
            raise UseCaseError("unknown backlog item '%s'" % backlog_id)
    for backlog_id in backlog_ids:
        store.add_artifact(work_id, "resolves", backlog_id)


def retire_resolved(store, work_id):
    for artifact in store.item_artifacts(work_id):
        if artifact.type != "resolves":
            continue
        if store.get_node(artifact.value).state != State.DONE:
            store.close(artifact.value, "resolved by %s" % work_id)
            store.add_artifact(artifact.value, "resolved-by", work_id)
