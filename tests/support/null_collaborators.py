class NoopWorktrees:
    def __init__(self):
        self.removed = []
        self.released = []

    def teardown_refusals(self, item, merged_prs=frozenset()):
        return []

    def pass_release_refusals(self, item, runs, merged_prs=frozenset()):
        return []

    def phase_release_refusals(self, run):
        return []

    def release_run(self, run, delete_remote=True):
        self.released.append(run.id)

    def remove(self, item):
        self.removed.append(item)


class NoFlow:
    def workspace_for_node(self, node):
        return None

    def phase_for(self, node):
        return None

    def workspace_for_phase(self, node, phase):
        return None
