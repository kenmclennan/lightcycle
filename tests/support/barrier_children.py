BARRIER_TIMEOUT = 60


def reap(procs):
    for p in procs:
        if p.is_alive():
            p.terminate()
    for p in procs:
        p.join()
