"""LinkArtifact: attach an artifact (pr, branch, spec, ...) to a story."""


class LinkArtifact:

    def __init__(self, store):
        self._store = store

    def execute(self, story, atype, value, label=None):
        self._store.add_artifact(story, atype, value, label)
