SCHEDULE_KEY_PREFIX = "schedule-"
WORKFLOW_KEY_PREFIX = "workflow-"


def schedule_blocks(values):
    return {
        k[len(SCHEDULE_KEY_PREFIX):]: dict(v)
        for k, v in values.items()
        if k.startswith(SCHEDULE_KEY_PREFIX) and isinstance(v, dict)
    }


def workflow_config_block_name(origin, name):
    return "%s%s-%s" % (WORKFLOW_KEY_PREFIX, origin, name)


def workflow_config(values, origin, name):
    block = values.get(workflow_config_block_name(origin, name))
    return dict(block) if isinstance(block, dict) else {}


def is_obsolete_key(key, value, seed_names):
    return (
        key not in seed_names and not key.startswith(SCHEDULE_KEY_PREFIX)
        and not (key.startswith(WORKFLOW_KEY_PREFIX) and isinstance(value, dict)))
