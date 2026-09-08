def format_elapsed(seconds):
    total_seconds = int(seconds)
    if total_seconds < 60:
        return "%ds" % total_seconds
    minutes = total_seconds // 60
    if minutes < 60:
        return "%dm" % minutes
    hours, minutes = divmod(minutes, 60)
    return "%dh %dm" % (hours, minutes)


def format_wall_and_active(wall_seconds, active_seconds):
    return "%s (%s active)" % (format_elapsed(wall_seconds), format_elapsed(active_seconds))
