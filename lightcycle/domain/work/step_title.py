def compose_step_title(stage, item_title):
    return "%s: %s" % (stage, item_title) if item_title else (stage or "")
