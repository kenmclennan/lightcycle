def worker_log_filename(role, spawnid):
    return "worker-%s-%s.log" % (role, spawnid)


def gh_calls_filename(spawnid):
    return "gh-calls-%s.log" % spawnid
