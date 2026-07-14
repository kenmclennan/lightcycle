def versions_to_prune(versions_newest_first, keep_n, pinned):
    return [
        sha
        for i, sha in enumerate(versions_newest_first)
        if i >= keep_n and sha not in pinned
    ]
