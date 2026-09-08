def item_active_seconds(steps):
    return sum(step.active_seconds or 0 for step in steps)
